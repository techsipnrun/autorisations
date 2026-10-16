// POST protégé par CSRF : un simple GET ne consomme jamais de numéro.
const reservationForm = document.querySelector("[data-reserver-avis]");
if (reservationForm) {
    reservationForm.querySelector("button").disabled = true;
    reservationForm.submit();
}
