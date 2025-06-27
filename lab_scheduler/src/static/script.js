
// script.js MODIFICADO — permite prosseguir mesmo sem horários selecionados

document.addEventListener("DOMContentLoaded", () => {
    const proceedToBookingButton = document.getElementById("proceedToBookingButton");
    const bookingModal = document.getElementById("bookingModal");
    const closeModalButton = document.querySelector(".close-button");
    const modalBookingForm = document.getElementById("modalBookingForm");
    const selectedSlotsSummaryList = document.querySelector("#selectedSlotsSummary ul");
    const modalFormMessage = document.getElementById("modalFormMessage");

    // Libera botão mesmo sem horários selecionados
    proceedToBookingButton.disabled = false;

    proceedToBookingButton.addEventListener("click", () => {
        updateSelectedSlotsSummary();
        bookingModal.style.display = "block";
    });

    closeModalButton.addEventListener("click", () => {
        bookingModal.style.display = "none";
    });

    modalBookingForm.addEventListener("submit", async (e) => {
        e.preventDefault();

        const formData = new FormData(modalBookingForm);
        const requestData = {
            user_name: formData.get("userName"),
            user_email: formData.get("userEmail"),
            coordinator_name: formData.get("coordinatorName"),
            observation: formData.get("observation") || "",
            slots: getSelectedSlots() // pode estar vazio
        };

        try {
            const response = await fetch("/api/bookings", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(requestData)
            });

            const result = await response.json();
            modalFormMessage.textContent = result.message || "Enviado!";
        } catch (err) {
            modalFormMessage.textContent = "Erro ao enviar.";
        }
    });

    function getSelectedSlots() {
        const selected = document.querySelectorAll("td.selected");
        return Array.from(selected).map(td => ({
            room_id: parseInt(td.dataset.roomId),
            booking_date: td.dataset.date,
            period: td.dataset.period
        }));
    }

    function updateSelectedSlotsSummary() {
        selectedSlotsSummaryList.innerHTML = "";
        const slots = getSelectedSlots();
        if (slots.length === 0) {
            const li = document.createElement("li");
            li.innerText = "Nenhum horário selecionado.";
            selectedSlotsSummaryList.appendChild(li);
        } else {
            slots.forEach(s => {
                const li = document.createElement("li");
                li.innerText = `${s.booking_date} - ${s.period}`;
                selectedSlotsSummaryList.appendChild(li);
            });
        }
    }
});
