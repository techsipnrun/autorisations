"""Interface réelle dans Chrome ; API et Leaflet simulés, aucun service distant."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import tempfile
from threading import Thread
from types import SimpleNamespace
from unittest import skipUnless
from urllib.parse import urlsplit

from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase

from instruction.utils.cartographie import CONTROLES, configurations_par_defaut, sources_par_defaut
from instruction.views.cartographie import convertir_source


CHROME = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")


@skipUnless(CHROME.exists(), "Chrome headless n’est pas installé.")
class CartographieInterfaceTests(SimpleTestCase):
    def test_configuration_apercu_sources_et_responsif(self):
        src = Path(__file__).resolve().parents[2]
        sources = sources_par_defaut()
        for identifiant, source in enumerate(sources, 1):
            source.update(id=identifiant, url_source=source["url"], importe=False)
        par_code = {source["code"]: source["id"] for source in sources}
        configurations = configurations_par_defaut()
        for configuration in configurations.values():
            for source in configuration["sources"]:
                source.update(id=par_code[source["code"]], url_source=source["url"], importe=False)
        sources.append({**sources[4], "id": 9, "code": "test-inactif", "nom": "test", "actif": False, "importe": True, "url_source": "", "url": "/cartographie/couche/9/?v=inactif"})
        sources.append({**sources[4], "id": 10, "code": "nouvelle-active", "nom": "Couche à ajouter", "importe": True, "url_source": "", "url": "/cartographie/couche/10/?v=nouvelle"})
        donnees = {"sources": sources, "configurations": configurations, "controles": CONTROLES}
        mock = """
        const payload = PAYLOAD;
        window.mapTests = []; window.posts = []; window.gets = []; window.conversionRequests = 0; window.confirm = () => window.acceptConfirm;
        window.acceptConfirm = true;
        let rejectSave = false;
        const feature = {type:'Feature', properties:{secteur:'nord'}, geometry:{type:'Point',coordinates:[55,-21]}};
        window.fetch = async (url, options = {}) => {
            if (options.method === 'POST') {
                if (url.endsWith('/convertir/')) { window.conversionRequests++; return nativeFetch(url, options); }
                window.posts.push({url, body: options.body});
                if (url.endsWith('/supprimer/')) return new Response(JSON.stringify({success:true}));
                if (url.includes('/source/')) {
                    const data = JSON.parse(options.body.get('configuration'));
                    return new Response(JSON.stringify({success:true, source:{...data, id:99, code:'nouvelle', url_source:data.url}}));
                }
                if (rejectSave) return new Response(JSON.stringify({erreur:'Échec simulé'}), {status:400});
                // État serveur simulé, indépendant des brouillons de l’interface.
                const code = url.split('/carte/')[1].split('/')[0];
                const data = JSON.parse(options.body);
                payload.configurations[code] = {...payload.configurations[code], options:data.options,
                    sources:data.sources.map((membre, ordre)=>({...payload.sources.find(source=>source.id===membre.id), ...membre, ordre}))};
                return new Response(JSON.stringify({success:true}));
            }
            window.gets.push(url);
            if (url === '/back-office/cartographie/') return new Response(JSON.stringify(payload));
            if (url.includes('/couche/9/') && !url.includes('apercu=1')) return new Response('{}', {status:404});
            if (url.includes('/inaccessible')) return new Response('{}', {status:404});
            return new Response(JSON.stringify({type:'FeatureCollection',features:[feature]}));
        };
        class Layer {
            constructor(options={}) { this.options=options; }
            addTo(map) { map.layers.add(this); this.map=map; return this; }
            bindPopup(content) { this.popup=content; return this; }
            bindTooltip(content) { this.tooltip=content; return this; }
        }
        class MapTest {
            constructor(id, options) { this.id=id; this.options=options; this.layers=new Set(); this.panes={}; this._leaflet_id=mapTests.length+1; mapTests.push(this); }
            setView(centre, zoom) { this.centre=centre; this.zoom=zoom; return this; }
            on() { return this; }
            createPane(name) { return this.panes[name]={style:{}}; }
            hasLayer(layer) { return this.layers.has(layer); }
            removeLayer(layer) { this.layers.delete(layer); return this; }
            invalidateSize() { return this; }
            remove() { this.removed=true; document.getElementById(this.id).replaceChildren(); }
        }
        window.L = {
            map:(id, options)=>new MapTest(id,options),
            tileLayer:(url, options)=>new Layer({...options,url}),
            geoJSON:(data, options)=>{
                const layer = new Layer(options);
                layer.children = (data.features || [data]).map(f=>{
                    const child = new Layer({...options, ...options.style(f)});
                    child.feature=f;
                    options.onEachFeature?.(f,child); return child;
                });
                return layer;
            },
            polygon:(points, style)=>new Layer({...style,sample:true}),
            polyline:(points, style)=>new Layer({...style,sample:true}),
            marker:(point, options)=>new Layer(options),
            circleMarker:(point, options)=>new Layer(options), divIcon:options=>options,
            DomUtil:{create:(tag, className)=>{const node=document.createElement(tag);node.className=className;return node;}},
            DomEvent:{disableClickPropagation:()=>{},disableScrollPropagation:()=>{}}, control:{},
            Control:{extend: definition=>class {
                addTo(map) { this.node=definition.onAdd.call(this,map); document.getElementById(map.id).append(this.node); return this; }
                getContainer() { return this.node; }
            }}
        };
        """.replace("PAYLOAD", json.dumps(donnees, ensure_ascii=True))
        body = render_to_string("instruction/refacto/back_office_cartographie.html", {"csrf_token": "test"})
        script = """
        window.addEventListener('load', async () => {
            const output = document.createElement('pre'); output.id='browser-test-result';document.body.append(output);
            const wait = () => new Promise(resolve=>setTimeout(resolve,50));
            const assert = (condition, texte) => { if(!condition) throw new Error(texte); };
            try {
                await wait();
                let root=document.getElementById('bo-cartographie');
                let form=root.querySelector('[data-carto-config-form]');
                let select=root.querySelector('[data-carto-profil]');
                assert(select.options.length===8, 'Sept profils et un choix vide chargés');
                assert(select.value==='', 'Aucun contexte sélectionné par défaut');
                assert(!root.querySelector('.bo-carto-workspace').hidden, 'Interface chargée à la demande');
                assert(mapTests.length===1, 'Aperçu créé');
                assert(mapTests.at(-1).centre.join(',')==='-21.1,55.5'&&mapTests.at(-1).zoom===11,'Aperçu Catalogue cadré sur La Réunion');
                assert([...mapTests.at(-1).layers].some(layer=>layer.options.url?.includes('data.geopf.fr')),'Plan IGN visible par défaut dans le Catalogue');
                let panel=root.closest('[data-panel]');
                // Recréer le module depuis les données serveur, sans bouton Actualiser.
                const rechargerInterface=async()=>{
                    const nouveau=panel.cloneNode(true);
                    panel.replaceWith(nouveau);panel=nouveau;
                    root=panel.querySelector('#bo-cartographie');delete root.dataset.vue;
                    root.querySelector('#bo-carto-preview-map').replaceChildren();
                    form=root.querySelector('[data-carto-config-form]');select=root.querySelector('[data-carto-profil]');
                    new Function(await nativeFetch('/static/instruction/js/back_office_cartographie.js').then(reponse=>reponse.text()))();
                    await wait();
                };
                assert(root.dataset.vue==='catalogue' && form.hidden,'Catalogue par défaut, personnalisation masquée');
                assert(!root.querySelector('[data-carto-source-select]'),'Aucun sélecteur déroulant de source');
                assert(!root.querySelector('[data-carto-recharger]')&&!root.querySelector('[data-carto-source-preview]'),'Anciens boutons Actualiser et Aperçu source supprimés');
                const previewButton=root.querySelector('[data-carto-preview]');
                assert(root.querySelectorAll('[data-carto-preview]').length===1&&previewButton.closest('.bo-carto-preview-heading'),'Un seul bouton d’aperçu dans l’en-tête de la carte');
                assert(previewButton.getBoundingClientRect().right<=root.querySelector('.bo-carto-preview-card').getBoundingClientRect().right,'Bouton aperçu contenu dans la carte');
                const sections=root.querySelectorAll('.bo-carto-catalogue-section');
                assert(sections.length===2&&[...sections].every(section=>section.open),'Deux listes ouvertes par défaut');
                const fonds=root.querySelector('[data-carto-catalogue-sources=tuiles]');
                assert([...fonds.children].map(button=>button.textContent).join('|')==='OpenStreetMap|OpenTopoMap|Plan IGN|Satellite','Liste des fonds triée');
                sections[0].querySelector('summary').click();assert(!sections[0].open&&sections[1].open,'Repli indépendant des listes');
                assert(fonds.querySelector('[data-carto-source-id="1"]').getAttribute('aria-pressed')==='true','Plan IGN mis en évidence dans le catalogue');
                sections[0].querySelector('summary').click();
                assert([...mapTests.at(-1).layers].filter(layer=>layer.options.sample||layer.options.icon).length===3,'Trois géométries du pétitionnaire conservées');
                assert(![...mapTests.at(-1).layers].some(layer=>layer.options.name),'Aucune couche visible dans le catalogue par défaut');
                previewButton.click();await wait();
                assert(![...mapTests.at(-1).layers].some(layer=>layer.options.name)&&posts.length===0,'Actualiser le catalogue sans source garde la carte sans couche et sans écriture');
                assert(payload.configurations.preinstruction_dn.sources.some(source=>source.code==='coeur'&&source.visible),'Visibilité métier du cœur inchangée');
                const menus=root.querySelectorAll('.agida-map-menus details');
                assert(menus.length===2,'Menus Fonds et Couches disponibles');
                assert(menus[0].querySelector('input:checked')?.parentElement.textContent==='Plan IGN','Plan IGN sélectionné dans le menu des fonds');
                menus[0].querySelector('summary').click();await wait();
                assert(menus[0].open&&!menus[1].open,'Fonds ouvert seul');
                menus[1].querySelector('summary').click();await wait();
                assert(!menus[0].open&&menus[1].open,'Couches ferme Fonds');
                const label=menus[1].querySelector('label');
                assert(getComputedStyle(label).flexDirection==='row'&&getComputedStyle(label).alignItems==='center','Cases alignées horizontalement malgré CSS back-office');
                const rect=label.querySelector('input').getBoundingClientRect();
                const range=document.createRange();range.selectNodeContents(label.lastChild);const texte=range.getBoundingClientRect();
                assert(Math.abs(rect.y+rect.height/2-texte.y-texte.height/2)<3,'Case et libellé sur la même ligne');
                menus[0].querySelector('summary').click();await wait();
                assert(menus[0].open&&!menus[1].open,'Fonds ferme Couches');
                menus[0].querySelector('summary').click();
                const preview=document.getElementById('bo-carto-preview-map');
                const catalogueHeight=preview.getBoundingClientRect().height;
                if(innerWidth>1200) assert(preview.getBoundingClientRect().width>root.querySelector('.bo-carto-settings').getBoundingClientRect().width,'Aperçu plus large que le formulaire du catalogue');
                panel.dataset.cartoVue='cartes';await wait();
                assert(form.hidden && root.querySelector('[data-carto-catalogue]').hidden,'Aucun formulaire sans contexte sélectionné');
                assert(root.querySelector('[data-carto-title]').textContent==='Personnaliser les cartes','Titre de rubrique');
                select.value='preinstruction_dn';select.dispatchEvent(new Event('change'));await wait();
                assert(!form.hidden,'Formulaire affiché après sélection d’un contexte');
                const sourceSections=[...form.querySelectorAll(':scope > details')].slice(0,2);
                assert(sourceSections.map(section=>section.querySelector('summary').textContent).join('|')==='Fonds de carte|Couches cartographiques','Fonds et couches sont des sections repliables');
                assert(sourceSections.every(section=>!section.open),'Fonds et couches repliés par défaut');
                sourceSections.forEach(section=>section.querySelector('summary').click());
                assert(sourceSections.every(section=>section.open),'Fonds et couches peuvent être dépliés');
                if(innerWidth>1200) {
                    assert(catalogueHeight>preview.getBoundingClientRect().height,'Aperçu du catalogue plus haut');
                    assert(preview.getBoundingClientRect().width>root.querySelector('.bo-carto-settings').getBoundingClientRect().width,'Personnalisation donnant davantage de largeur à la carte');
                    assert(panel.getBoundingClientRect().width>1120,'Panneau Carto non limité à la largeur historique');
                }
                assert(form.querySelector('[data-carto-sources=tuiles]').children.length===4,'Fonds dans une liste dédiée');
                assert(form.querySelector('[data-carto-sources=geojson]').children.length===5,'Couches actives dans une liste dédiée');
                const color=form.querySelector('[data-style=color]');color.value='#123456';color.dispatchEvent(new Event('input',{bubbles:true}));
                assert(form.classList.contains('is-dirty'), 'Modifications non enregistrées signalées');
                root.querySelector('[data-carto-preview]').click();await wait();
                assert([...mapTests.at(-1).layers].some(layer=>layer.options.sample&&layer.options.color==='#123456'),'Couleur de travail appliquée');
                assert(mapTests.at(-1).options.zoomControl===true,'Contrôles transmis au moteur');
                assert(posts.length===0,'Aperçu sans écriture');
                const arrows=form.querySelectorAll('.bo-carto-row-buttons button');arrows[1].click();
                assert(form.querySelector('[data-style=fillOpacity]').validity.valid,'L’opacité par défaut 0,28 ne doit pas bloquer l’enregistrement');
                form.querySelector('[type=submit]').click();await wait();
                const saved=JSON.parse(posts.at(-1).body);
                assert(saved.sources[0].id===2,'Ordre des sources enregistré');
                assert(saved.options.geometrie.color==='#123456','Style enregistré');
                assert(!form.classList.contains('is-dirty'),'État propre après succès');
                const fillOpacity=form.querySelector('[data-style=fillOpacity]');
                const geometryDetails=fillOpacity.closest('details');
                geometryDetails.open=false;fillOpacity.value='1.1';
                fillOpacity.dispatchEvent(new Event('input',{bubbles:true}));
                form.querySelector('[type=submit]').click();await wait();
                assert(posts.length===1,'Valeur hors limites : aucune requête envoyée');
                assert(geometryDetails.open&&root.querySelector('[data-carto-config-status]').classList.contains('is-error'),'Champ invalide dévoilé et erreur visible');
                assert(root.querySelector('[data-carto-config-status]').textContent.includes('Opacité de remplissage'),'Erreur identifiant le champ bloquant');
                fillOpacity.value='0.28';geometryDetails.open=false;
                rejectSave=true; color.value='#654321';color.dispatchEvent(new Event('input',{bubbles:true}));
                form.querySelector('[type=submit]').click();await wait();
                assert(form.classList.contains('is-dirty')&&root.querySelector('[data-carto-config-status]').textContent.includes('Échec'),'Échec conservant les modifications');
                rejectSave=false;
                select.value='edition';select.dispatchEvent(new Event('change'));await wait();
                assert(form.querySelector('[data-controle=editMode]'),'Outils de dessin disponibles dans Édition');
                select.value='instruction_dm';select.dispatchEvent(new Event('change'));await wait();
                assert(!form.querySelector('[data-controle=editMode]'),'Pas d’édition sur les dossiers DM');
                panel.dataset.cartoVue='catalogue';await wait();
                assert(form.hidden && !root.querySelector('[data-carto-catalogue]').hidden,'Retour au catalogue');
                const sourceForm=root.querySelector('[data-carto-source-form]');
                root.querySelector('[data-carto-source-id="5"]').click();await wait();
                assert(!sourceForm.hidden&&sourceForm.dataset.id==='5','Édition directe depuis la liste');
                assert([...mapTests.at(-1).layers].filter(layer=>layer.options.name).length===1,'Seule la couche choisie explicitement est prévisualisée');
                const properties=root.querySelector('#bo-carto-properties');
                assert(properties.children.length===1&&properties.children[0].value==='secteur','Suggestions de propriétés depuis le GeoJSON existant');
                assert(gets.filter(url=>url===sourceForm.elements.url.value).length===1,'Détection et aperçu partagent le cache GeoJSON');
                assert(sourceForm.elements.popup_texte.disabled&&sourceForm.elements.popup_propriete.disabled,'Informations désactivées si Aucune');
                sourceForm.elements.popup_mode.value='clic';sourceForm.elements.popup_mode.dispatchEvent(new Event('change'));
                assert(!sourceForm.elements.popup_texte.disabled&&!sourceForm.elements.popup_propriete.disabled,'Informations réactivées pour Au clic');
                sourceForm.elements.popup_texte.value='Texte conservé';
                sourceForm.elements.popup_mode.value='aucun';sourceForm.elements.popup_mode.dispatchEvent(new Event('change'));
                assert(sourceForm.elements.popup_texte.value==='Texte conservé','Désactiver ne supprime pas le texte');
                assert(!root.querySelector('[data-carto-source-origin]'),'Pas de section Source et crédits');
                const helps=sourceForm.querySelectorAll('.back-office-acte-help');
                assert(helps.length===5,'Cinq aides : nom, URL, attribution, import et propriété');
                assert(sourceForm.querySelector('[aria-describedby="bo-carto-property-help"]').textContent.includes('GPX/KML'),'Aide sur les propriétés issues de la conversion');
                const nameHelp=sourceForm.querySelector('[aria-describedby="bo-carto-name-help"]');
                assert(nameHelp.querySelector('[role=tooltip]').textContent.includes('menus')&&nameHelp.querySelector('[role=tooltip]').textContent.includes('légende'),'Aide expliquant où apparaît le nom');
                assert(sourceForm.elements.nom.required&&sourceForm.elements.nom.labels[0].htmlFor==='bo-carto-source-name','Nom toujours obligatoire et relié à son label');
                const urlHelp=sourceForm.querySelector('[aria-describedby="bo-carto-url-help"]');
                urlHelp.focus();await wait();
                const bubble=urlHelp.querySelector('[role=tooltip]');
                assert(getComputedStyle(bubble).visibility==='visible'&&bubble.textContent.includes('Alternative'),'Explication URL au focus');
                assert(bubble.textContent.includes('chemin')&&bubble.textContent.includes('HTTP(S)'),'Aide des couches : chemins statiques et URL distantes');
                assert(getComputedStyle(urlHelp).cursor==='default','Pas de curseur point d’interrogation');
                assert(bubble.getBoundingClientRect().left>=0&&bubble.getBoundingClientRect().right<=innerWidth,'Aide contenue dans le viewport');
                urlHelp.blur();
                const number=sourceForm.querySelector('[data-style=weight]');
                assert(number.getBoundingClientRect().width<130,'Épaisseur : champ numérique compact');
                root.querySelector('[data-carto-source-id="9"]').click();await wait();
                const previewStatus=root.querySelector('[data-carto-preview-status]');
                assert(previewStatus.classList.contains('is-error')&&previewStatus.textContent.includes('n’est pas active'),'Message clair pour une couche inactive');
                assert(![...mapTests.at(-1).layers].some(layer=>layer.options.name==='test'),'Couche inactive non ajoutée à la carte');
                sourceForm.elements.actif.checked=true;
                root.querySelector('[data-carto-preview]').click();await wait();
                assert([...mapTests.at(-1).layers].some(layer=>layer.options.name==='test'),'Couche importée réactivée en aperçu sans enregistrer');
                assert(!previewStatus.textContent&&mapTests.at(-1).layers.size>0,'Message inactif retiré après aperçu actif');
                assert(!payload.sources.find(source=>source.id===9).actif&&posts.length===2,'Aperçu sans réactivation ni écriture en base');
                assert(gets.filter(url=>url.includes('/couche/9/')).every(url=>url.includes('apercu=1')),'Lecture importée par URL réservée à l’aperçu admin');
                sourceForm.elements.actif.checked=false;
                root.querySelector('[data-carto-preview]').click();await wait();
                assert(previewStatus.textContent.includes('n’est pas active')&&![...mapTests.at(-1).layers].some(layer=>layer.options.name==='test'),'Retour à un aperçu inactif sans couche');
                root.querySelector('[data-carto-new-source=tuiles]').click();
                assert(sourceForm.elements.format.value==='tuiles'&&!root.querySelector('[data-carto-tile-fields]').hidden,'Ajout de fond');
                assert(sourceForm.elements.attribution.required&&root.querySelector('[data-carto-url-hint]').textContent.includes('{z}'),'URL et attribution accessibles avec aide adaptée aux fonds');
                const tileHelp=root.querySelector('[data-carto-url-hint]');
                urlHelp.focus();await wait();
                assert(tileHelp.scrollWidth<=tileHelp.clientWidth,'URL IGN longue sans débordement de la bulle');
                urlHelp.blur();
                assert(sourceForm.elements.maxZoom.getBoundingClientRect().width<130,'Zoom maximal compact');
                root.querySelector('[data-carto-new-source=geojson]').click();
                assert(sourceForm.elements.url.placeholder==='/static/instruction/carto/fond_coeur_de_parc.geojson'&&!sourceForm.elements.url.placeholder.includes('{z}'),'Placeholder GeoJSON distinct du fond de tuiles');
                assert(properties.children.length===0,'Propriétés réinitialisées pour une nouvelle couche');
                const uploaded=new DataTransfer();
                uploaded.items.add(new File([JSON.stringify({type:'FeatureCollection',features:[{...feature,properties:{nom:'Nord',secteur:'nord'}},{...feature,properties:{commune:'Test'}}]})],'essai.geojson',{type:'application/geo+json'}));
                sourceForm.elements.fichier.files=uploaded.files;sourceForm.elements.fichier.dispatchEvent(new Event('change'));await wait();
                assert([...properties.children].map(option=>option.value).join('|')==='commune|nom|secteur','Toutes les propriétés du fichier importé sont proposées et triées');
                sourceForm.elements.nom.value='Couche importée';
                sourceForm.querySelector('[data-style=color]').value='#123abc';
                root.querySelector('[data-carto-preview]').click();
                for(let tentative=0;tentative<20&&!root.querySelector('[data-carto-source-status]').textContent;tentative++) await wait();
                const importedPreview=[...mapTests.at(-1).layers].find(layer=>layer.options.name===sourceForm.elements.nom.value);
                assert(importedPreview,'Le fichier importé est prévisualisé sans enregistrement');
                assert(importedPreview.children.length===2&&importedPreview.children[0].options.color==='#123abc','Bouton partagé : aperçu du fichier importé et du style non enregistré');
                const importStatus=root.querySelector('[data-carto-import-status]');
                const imports=[
                    ['parcours.gpx','<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1"><trk><name>Trace Mafate</name><trkseg><trkpt lat="-21" lon="55"/><trkpt lat="-21.1" lon="55.1"/></trkseg></trk></gpx>','LineString','Trace Mafate'],
                    ['lieux.kml','<kml xmlns="http://www.opengis.net/kml/2.2"><Placemark><name>Îlet</name><ExtendedData><Data name="secteur"><value>nord</value></Data></ExtendedData><Point><coordinates>55,-21</coordinates></Point></Placemark></kml>','Point','Îlet']
                ];
                for(const [name,xml,type,nom] of imports) {
                    const avant=conversionRequests;
                    const transfer=new DataTransfer();transfer.items.add(new File([xml],name,{type:'application/xml'}));
                    sourceForm.elements.fichier.files=transfer.files;sourceForm.elements.fichier.dispatchEvent(new Event('change'));
                    for(let tentative=0;tentative<40&&!importStatus.textContent.startsWith('Fichier converti');tentative++) await wait();
                    assert(importStatus.textContent.startsWith('Fichier converti'),name+' converti côté serveur : '+importStatus.textContent);
                    assert([...properties.children].some(option=>option.value==='nom'),'Nom proposé après conversion '+name);
                    sourceForm.elements.popup_mode.value='clic';sourceForm.elements.popup_mode.dispatchEvent(new Event('change'));
                    sourceForm.elements.popup_propriete.value='nom';
                    root.querySelector('[data-carto-preview]').click();await wait();
                    const layer=[...mapTests.at(-1).layers].find(layer=>layer.options.name===sourceForm.elements.nom.value);
                    assert(layer.children[0].feature.geometry.type===type,'Géométrie convertie affichée '+name);
                    assert(layer.children[0].popup.textContent===nom,'Propriété convertie utilisable dans le popup '+name);
                    assert(conversionRequests===avant+1,'Une seule conversion partagée entre propriétés et aperçu '+name);
                    assert(posts.length===2,'Conversion et aperçu sans sauvegarde de source '+name);
                }
                const invalid=new DataTransfer();invalid.items.add(new File(['<kml>'],'invalide.kml',{type:'application/xml'}));
                sourceForm.elements.fichier.files=invalid.files;sourceForm.elements.fichier.dispatchEvent(new Event('change'));
                for(let tentative=0;tentative<40&&!importStatus.classList.contains('is-error');tentative++) await wait();
                assert(importStatus.classList.contains('is-error')&&importStatus.textContent.includes('XML mal formé'),'Erreur de conversion claire et rouge');
                assert(![...mapTests.at(-1).layers].some(layer=>layer.options.name===sourceForm.elements.nom.value),'L’ancien aperçu n’est pas conservé après import invalide');
                root.querySelector('[data-carto-preview]').click();
                for(let tentative=0;tentative<40&&!previewStatus.classList.contains('is-error');tentative++) await wait();
                assert(previewStatus.textContent.includes('XML mal formé'),'Erreur visible dans l’aperçu');
                sourceForm.querySelector('[type=submit]').click();
                for(let tentative=0;tentative<40&&!root.querySelector('[data-carto-source-status]').classList.contains('is-error');tentative++) await wait();
                assert(posts.length===2,'Import invalide : aucun enregistrement envoyé');
                sourceForm.elements.fichier.value='';
                sourceForm.elements.url.value='https://example.test/inaccessible';sourceForm.elements.url.dispatchEvent(new Event('change'));await wait();
                assert(properties.children.length===0&&root.querySelector('[data-carto-properties-status]').textContent.includes('saisie manuelle'),'URL inaccessible : saisie libre toujours possible');
                sourceForm.elements.nom.value='Nouvelle couche';sourceForm.elements.url.value='https://example.test/couche.geojson';
                sourceForm.elements.url.dispatchEvent(new Event('change'));await wait();
                sourceForm.elements.attribution.value='<img src=x onerror=alert(1)>';
                root.querySelector('[data-carto-preview]').click();await wait();
                assert([...mapTests.at(-1).layers].find(layer=>layer.options.name==='Nouvelle couche').options.attribution==='&lt;img src=x onerror=alert(1)&gt;','Crédit de couche transmis sans HTML exécutable');
                assert(posts.length===2,'Aperçu de source sans écriture');
                sourceForm.querySelector('[type=submit]').click();await wait();
                assert(root.querySelector('[data-carto-source-id="99"]').getAttribute('aria-pressed')==='true','Source ajoutée et sélectionnée dans la liste');
                assert(root.querySelector('[data-carto-source-status]').textContent.includes('Source enregistrée'),'Confirmation de source');
                const supprimer=root.querySelector('[data-carto-source-delete]');
                assert(!supprimer.hidden,'Suppression proposée pour une source enregistrée');
                acceptConfirm=false;supprimer.click();await wait();
                assert(posts.length===3,'Annulation de suppression sans requête');
                acceptConfirm=true;supprimer.click();await wait();
                assert(posts.length===4&&posts.at(-1).url.endsWith('/99/supprimer/'),'Suppression confirmée');
                assert(!root.querySelector('[data-carto-source-id="99"]')&&supprimer.hidden&&sourceForm.hidden,'Catalogue actualisé après suppression');
                panel.dataset.cartoVue='cartes';await wait();
                select.value='edition';select.dispatchEvent(new Event('change'));await wait();
                const ligneCouche=nom=>[...form.querySelector('[data-carto-sources=geojson]').children].find(ligne=>ligne.querySelector('strong')?.textContent===nom);
                assert(!ligneCouche('Couche à ajouter').querySelector('input').checked,'Nouvelle couche non disponible initialement');
                ligneCouche('Couche à ajouter').querySelector('input').click();
                form.querySelector('[type=submit]').click();await wait();
                assert(payload.configurations.edition.sources.some(source=>source.id===10&&!source.visible),'Disponible ajouté côté serveur par vrai clic Enregistrer');
                await rechargerInterface();
                select.value='edition';select.dispatchEvent(new Event('change'));await wait();
                assert(ligneCouche('Couche à ajouter').querySelector('input').checked,'Disponible conservé après rechargement depuis le serveur');
                const copieEdition=JSON.parse(JSON.stringify(payload.configurations.edition));
                const controleEdition=AGIDACarto.configurer(mapTests.at(-1),'edition',copieEdition);await controleEdition.ready;
                assert(controleEdition.entrees.some(entree=>entree.source.id===10&&entree.input&&!entree.input.disabled),'Couche disponible proposée par le moteur de l’éditeur');
                ligneCouche('Couche à ajouter').querySelector('input').click();
                ligneCouche('Cœur du Parc national').querySelector('input').click();
                form.querySelector('[type=submit]').click();await wait();
                assert(!payload.configurations.edition.sources.some(source=>[5,10].includes(source.id)),'Disponible décoché retire les associations côté serveur');
                await rechargerInterface();
                select.value='edition';select.dispatchEvent(new Event('change'));await wait();
                assert(!ligneCouche('Couche à ajouter').querySelector('input').checked&&!ligneCouche('Cœur du Parc national').querySelector('input').checked,'Retraits conservés après rechargement');
                assert(!AGIDACarto.configurations.edition.sources.some(source=>[5,10].includes(source.id)),'Sources retirées absentes de la configuration transmise au moteur');
                assert(document.documentElement.scrollWidth<=innerWidth,'Pas de débordement horizontal');
                for(const name of ['formulaire_map.js','formulaire_map_manif_sportives.js','carto_test.js','requetes_carte.js','statistiques.js']) {
                    // Analyse syntaxique des adaptateurs sans exécuter leur logique métier.
                    const source = await nativeFetch('/static/instruction/js/'+name).then(r=>r.text());
                    try { new Function(source); } catch(error) { throw new Error(name+': '+error.message); }
                }
                output.textContent='CARTOGRAPHIE_OK';
            } catch(error) { output.textContent='ERREUR: '+error.message; }
        });
        """
        html = f'''<!doctype html><html lang="fr"><head><meta charset="utf-8">
        <link rel="stylesheet" href="/static/instruction/css/back_office.css">
        <link rel="stylesheet" href="/static/instruction/css/cartographie.css">
        <link rel="stylesheet" href="/static/instruction/css/back_office_cartographie.css">
        <style>body{{margin:0;padding:16px;font-family:Arial;box-sizing:border-box}}*{{box-sizing:border-box}}</style>
        <script>const nativeFetch=window.fetch;{mock}</script>
        <script src="/static/instruction/js/cartographie.js" defer></script>
        <script src="/static/instruction/js/back_office_types_actes.js" defer></script>
        <script src="/static/instruction/js/back_office_cartographie.js" defer></script>
        </head><body><section class="back-office-panel" data-panel="carto">{body}</section><script>{script}</script></body></html>'''

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_POST(self):
                if self.path != '/back-office/cartographie/convertir/':
                    self.send_error(404)
                    return
                request = RequestFactory().generic('POST', self.path, data=self.rfile.read(int(self.headers['Content-Length'])), content_type=self.headers['Content-Type'])
                request.user = SimpleNamespace(is_authenticated=True, is_superuser=True)
                reponse = convertir_source(request)
                self.send_response(reponse.status_code)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(reponse.content)

            def do_GET(self):
                path = urlsplit(self.path).path
                if path == "/":
                    content, content_type = html.encode("utf-8"), "text/html; charset=utf-8"
                elif path.startswith("/static/instruction/"):
                    resource = src / "instruction/static/instruction" / path.removeprefix("/static/instruction/")
                    content = resource.read_bytes()
                    content_type = "text/css" if resource.suffix == ".css" else "application/javascript"
                else:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.end_headers()
                self.wfile.write(content)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            for largeur in (540, 1600):
                with self.subTest(largeur=largeur), tempfile.TemporaryDirectory() as profile:
                    resultat = subprocess.run([
                        str(CHROME), "--headless=new", "--disable-gpu", "--no-first-run",
                        "--disable-background-networking", f"--window-size={largeur},1000",
                        f"--user-data-dir={profile}", "--virtual-time-budget=10000", "--dump-dom",
                        f"http://127.0.0.1:{server.server_port}/",
                    ], capture_output=True, timeout=45, creationflags=subprocess.CREATE_NO_WINDOW)
                    dom = resultat.stdout.decode("utf-8", errors="replace")
                    diagnostic = dom[dom.rfind('<pre id="browser-test-result">'):][:800] if dom else resultat.stderr.decode("utf-8", errors="replace")[-1500:]
                    self.assertTrue('<pre id="browser-test-result">CARTOGRAPHIE_OK</pre>' in dom, diagnostic)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
