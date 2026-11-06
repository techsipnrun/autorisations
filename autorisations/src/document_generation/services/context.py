"""Résolution explicite des balises connues et construction du contexte imbriqué."""

from collections.abc import Mapping
from types import MappingProxyType

from autorisations.models.models_generation import Balise

from .providers import KNOWN_PROVIDERS, ResolutionSource


class BaliseNonResolueError(ValueError):
    """Aucun provider Python n'est enregistré pour le code demandé."""


class BaliseResolver:
    def __init__(self, providers: Mapping | None = None):
        self.providers = MappingProxyType(dict(KNOWN_PROVIDERS if providers is None else providers))
        field = Balise._meta.get_field("code")
        for code, provider in self.providers.items():
            field.clean(code, None)
            if not callable(provider):
                raise TypeError(f"Le provider de {code} doit être appelable.")

    def resolve(self, code, source):
        try:
            provider = self.providers[code]
        except KeyError:
            raise BaliseNonResolueError(f"Aucun provider pour la balise connue {code}.") from None
        # Une erreur technique du provider doit rester visible, jamais devenir None.
        return provider(source)


class DocumentContextBuilder:
    def __init__(self, resolver=None):
        self.resolver = resolver if resolver is not None else BaliseResolver()

    def build(self, dossier, codes=None, balises=None):
        """Construit toutes les balises supportées, ou uniquement les codes demandés.

        Les codes proviennent du registre ou d'une liste explicite, pas d'un accès
        automatique au catalogue SQL. La validation métier required/allow_blank
        et les balises manuelles seront traitées aux prochaines étapes.
        """
        resolver = self.resolver
        if balises is not None:
            from .catalogue_sources import resolve_catalogue_source
            resolver = BaliseResolver({b.code: (lambda source, definition=b: resolve_catalogue_source(definition, source))
                                      for b in balises if b.mode == Balise.Mode.CONNUE})
        codes = tuple(dict.fromkeys(resolver.providers if codes is None else codes))
        # Vérifie toute la sélection avant de déclencher un accès aux données.
        for code in codes:
            if code not in resolver.providers:
                raise BaliseNonResolueError(f"Aucun provider pour la balise connue {code}.")
            if any(other.startswith(code + ".") for other in codes):
                raise ValueError(f"Collision entre la balise {code} et une balise imbriquée.")
        source = ResolutionSource(dossier)
        context = {}
        for code in codes:
            node = context
            parts = code.split(".")
            for part in parts[:-1]:
                node = node.setdefault(part, {})
            node[parts[-1]] = resolver.resolve(code, source)
        return context
