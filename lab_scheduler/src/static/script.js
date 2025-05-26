// /home/ubuntu/lab_scheduler/src/static/script.js

document.addEventListener("DOMContentLoaded", () => {
    // DOM Elements for Modal and New Flow
    const weekSelector = document.getElementById("weekSelector");
    const loadScheduleButton = document.getElementById("loadScheduleButton");
    const scheduleTableContainer = document.getElementById("scheduleTableContainer");
    const scheduleMessage = document.getElementById("scheduleMessage");
    const proceedToBookingButton = document.getElementById("proceedToBookingButton");

    const bookingModal = document.getElementById("bookingModal");
    const closeModalButton = document.querySelector(".close-button");
    const modalBookingForm = document.getElementById("modalBookingForm");
    const selectedSlotsSummaryList = document.querySelector("#selectedSlotsSummary ul");
    const modalFormMessage = document.getElementById("modalFormMessage");

    const API_BASE_URL = "/api";
    let allRooms = [];
    let selectedSlots = []; // Stores { roomId, roomName, date, period, cellRef }
    let currentFetchedBookings = [];
    let currentWeekStartDate;

    // --- Helper Functions for Date Handling (UTC) ---
    function getTodayUTC() {
        const today = new Date();
        return new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate()));
    }

    function parseDateStrToUTC(dateStr) {
        const [year, month, day] = dateStr.split("-").map(Number);
        return new Date(Date.UTC(year, month - 1, day));
    }

    // --- Helper Functions for Messages ---
    function showModalMessage(message, type) {
        modalFormMessage.textContent = message;
        modalFormMessage.className = `message ${type}`;
        if (type === "success") {
            setTimeout(() => {
                modalFormMessage.textContent = "";
                modalFormMessage.className = "message";
            }, 4000);
        }
    }

    function showScheduleMessage(message, type) {
        scheduleMessage.textContent = message;
        scheduleMessage.className = `message ${type}`;
        if (type !== "error" && type !== "info") { // Keep error and info messages longer or until next action
             setTimeout(() => {
                scheduleMessage.textContent = "";
                scheduleMessage.className = "message";
            }, 3000);
        }
    }

    // --- Room Data --- 
    async function fetchAllRooms() {
        try {
            const response = await fetch(`${API_BASE_URL}/rooms`);
            if (!response.ok) throw new Error(`Erro ao buscar salas: ${response.statusText}`);
            allRooms = await response.json();
        } catch (error) {
            console.error("Falha ao buscar salas:", error);
            showScheduleMessage("Não foi possível carregar dados das salas. Tente recarregar.", "error");
        }
    }

    // --- Schedule Logic (Loading and Rendering) ---
    async function loadScheduleData(selectedDateStr) {
        let startDate, endDate;
        const todayUTC = getTodayUTC();

        if (selectedDateStr) {
            const selectedDateObj = parseDateStrToUTC(selectedDateStr);
            // Ensure the selected week is not entirely in the past relative to server time (UTC)
            // We check the start of the week for this.
            const tempDate = new Date(selectedDateObj.valueOf()); // Clone to avoid modifying selectedDateObj
            const dayOfWeek = tempDate.getUTCDay();
            const diffToMonday = dayOfWeek === 0 ? -6 : 1 - dayOfWeek;
            startDate = new Date(tempDate.setUTCDate(tempDate.getUTCDate() + diffToMonday));
            
            // If the Friday of the selected week is in the past, show a message and don't load.
            const endOfWeekForCheck = new Date(startDate.valueOf());
            endOfWeekForCheck.setUTCDate(startDate.getUTCDate() + 4);
            if (endOfWeekForCheck < todayUTC && endOfWeekForCheck.toISOString().split("T")[0] !== todayUTC.toISOString().split("T")[0]) {
                showScheduleMessage("Não é possível carregar escalas de semanas completamente passadas.", "info");
                scheduleTableContainer.innerHTML = "<p>Selecione uma semana atual ou futura.</p>";
                return;
            }
            endDate = new Date(new Date(startDate).setUTCDate(startDate.getUTCDate() + 4));
        } else { // Default to current week
            const todayForLogic = new Date(); // Use local today to find current week's Monday
            const dayOfWeek = todayForLogic.getDay();
            const diffToMonday = dayOfWeek === 0 ? -6 : 1 - dayOfWeek;
            startDate = new Date(todayForLogic.setDate(todayForLogic.getDate() + diffToMonday));
            // Convert startDate to UTC for API call and logic
            startDate = parseDateStrToUTC(startDate.toISOString().split("T")[0]);
            endDate = new Date(new Date(startDate).setUTCDate(startDate.getUTCDate() + 4));
        }
        currentWeekStartDate = startDate; 

        const startDateStrAPI = startDate.toISOString().split("T")[0];
        const endDateStrAPI = endDate.toISOString().split("T")[0];
        
        showScheduleMessage("Carregando escala...", "");
        try {
            const response = await fetch(`${API_BASE_URL}/bookings?start_date=${startDateStrAPI}&end_date=${endDateStrAPI}`);
            if (!response.ok) throw new Error(`Erro ao buscar agendamentos: ${response.statusText}`);
            currentFetchedBookings = await response.json();
            if (allRooms.length === 0) await fetchAllRooms();
            
            renderScheduleTable(currentFetchedBookings, allRooms, currentWeekStartDate);
            showScheduleMessage("Escala carregada.", "success");
        } catch (error) {
            console.error("Falha ao carregar escala:", error);
            showScheduleMessage("Não foi possível carregar a escala.", "error");
            scheduleTableContainer.innerHTML = "<p>Erro ao carregar escala.</p>";
        }
    }

    function renderScheduleTable(bookings, roomsData, weekStartDateObj) {
        scheduleTableContainer.innerHTML = "";
        selectedSlots = [];
        updateProceedButtonState();
        const todayUTC = getTodayUTC();

        const table = document.createElement("table");
        const thead = document.createElement("thead");
        const tbody = document.createElement("tbody");

        const headerRow = document.createElement("tr");
        headerRow.innerHTML = "<th>Sala</th>";
        const days = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta"];
        const periods = ["Manhã", "Tarde"];
        const datesOfWeek = [];

        for (let i = 0; i < 5; i++) {
            const currentDate = new Date(weekStartDateObj.valueOf());
            currentDate.setUTCDate(weekStartDateObj.getUTCDate() + i);
            datesOfWeek.push(currentDate.toISOString().split("T")[0]);
            const th = document.createElement("th");
            th.colSpan = 2;
            th.textContent = `${days[i]} (${currentDate.toLocaleDateString("pt-BR", {day:"2-digit", month:"2-digit", timeZone: "UTC"})})`;
            headerRow.appendChild(th);
        }
        thead.appendChild(headerRow);

        const subHeaderRow = document.createElement("tr");
        subHeaderRow.innerHTML = "<td></td>";
        for (let i = 0; i < 5; i++) {
            periods.forEach(p => {
                const th = document.createElement("th");
                th.textContent = p;
                subHeaderRow.appendChild(th);
            });
        }
        thead.appendChild(subHeaderRow);
        table.appendChild(thead);

        roomsData.sort((a,b) => a.id - b.id).forEach(room => {
            const row = document.createElement("tr");
            const roomCell = document.createElement("td");
            roomCell.textContent = room.name;
            row.appendChild(roomCell);

            datesOfWeek.forEach(dateStr => {
                const slotDateUTC = parseDateStrToUTC(dateStr);
                const isPastDate = slotDateUTC < todayUTC;

                periods.forEach(period => {
                    const cell = document.createElement("td");
                    const booking = bookings.find(b => 
                        b.room_id === room.id && 
                        b.booking_date === dateStr && 
                        b.period === period
                    );
                    if (booking) {
                        cell.textContent = booking.user_name;
                        cell.classList.add("booked");
                    } else if (isPastDate) {
                        cell.textContent = "Indisponível";
                        cell.classList.add("past"); // Add a new class for past, unbookable slots
                    } else {
                        cell.textContent = "Disponível";
                        cell.classList.add("available");
                        cell.dataset.roomId = room.id;
                        cell.dataset.roomName = room.name;
                        cell.dataset.date = dateStr;
                        cell.dataset.period = period;
                        cell.addEventListener("click", handleSlotClick);
                    }
                    row.appendChild(cell);
                });
            });
            tbody.appendChild(row);
        });
        table.appendChild(tbody);
        scheduleTableContainer.appendChild(table);
    }

    function handleSlotClick(event) {
        const cell = event.currentTarget;
        if (cell.classList.contains("booked") || cell.classList.contains("past")) return;

        const slotDateStr = cell.dataset.date;
        const slotDateUTC = parseDateStrToUTC(slotDateStr);
        const todayUTC = getTodayUTC();

        if (slotDateUTC < todayUTC) {
            showScheduleMessage("Não é possível selecionar datas/horários passados.", "error");
            // Visually revert if it was somehow selected or state changed, though 'past' class should prevent click.
            cell.classList.remove("selected");
            cell.classList.add("available"); // Or add 'past' if not already there
            cell.textContent = "Disponível"; // Or "Passado"
            return;
        }

        const slotData = {
            roomId: parseInt(cell.dataset.roomId),
            roomName: cell.dataset.roomName,
            date: slotDateStr,
            period: cell.dataset.period,
            cellRef: cell
        };

        const existingIndex = selectedSlots.findIndex(s => 
            s.roomId === slotData.roomId && 
            s.date === slotData.date && 
            s.period === slotData.period
        );

        if (existingIndex > -1) {
            selectedSlots.splice(existingIndex, 1);
            cell.classList.remove("selected");
            cell.textContent = "Disponível";
        } else {
            selectedSlots.push(slotData);
            cell.classList.add("selected");
            cell.textContent = "Selecionado";
        }
        updateProceedButtonState();
    }

    function updateProceedButtonState() {
        proceedToBookingButton.disabled = selectedSlots.length === 0;
    }

    // --- Modal Logic ---
    function openBookingModal() {
        if (selectedSlots.length === 0) {
            showScheduleMessage("Nenhum horário selecionado.", "error");
            return;
        }
        // Double check for past dates before opening modal
        const todayUTC = getTodayUTC();
        for (const slot of selectedSlots) {
            if (parseDateStrToUTC(slot.date) < todayUTC) {
                showScheduleMessage("Um ou mais horários selecionados estão no passado e não podem ser agendados. Por favor, desmarque-os.", "error");
                // Optionally, could auto-deselect them here and update UI
                return;
            }
        }

        selectedSlotsSummaryList.innerHTML = "";
        selectedSlots.forEach(slot => {
            const li = document.createElement("li");
            li.textContent = `${slot.roomName} - ${new Date(slot.date + 'T00:00:00').toLocaleDateString('pt-BR', {timeZone: 'UTC'})} - ${slot.period}`;
            selectedSlotsSummaryList.appendChild(li);
        });
        modalBookingForm.reset();
        showModalMessage("", "");
        bookingModal.style.display = "block";
    }

    function closeBookingModal() {
        bookingModal.style.display = "none";
    }

    async function handleModalFormSubmit(event) {
        event.preventDefault();
        const formData = new FormData(modalBookingForm);
        const requestData = {
            user_name: formData.get("userName"),
            user_email: formData.get("userEmail"),
            coordinator_name: formData.get("coordinatorName"),
            slots: selectedSlots.map(s => ({ 
                room_id: s.roomId, 
                booking_date: s.date, 
                period: s.period 
            }))
        };

        if (requestData.slots.length === 0) {
            showModalMessage("Nenhum horário foi selecionado para agendar.", "error");
            return;
        }

        showModalMessage("Processando agendamento...", "");
        try {
            const response = await fetch(`${API_BASE_URL}/bookings`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(requestData)
            });
            const result = await response.json();
            if (response.ok && response.status === 201) {
                showModalMessage(result.message || "Agendamento(s) realizado(s) com sucesso!", "success");
                selectedSlots.forEach(slot => {
                    slot.cellRef.classList.remove('selected', 'available');
                    slot.cellRef.classList.add('booked');
                    slot.cellRef.textContent = requestData.user_name;
                    slot.cellRef.removeEventListener('click', handleSlotClick);
                });
                selectedSlots = [];
                updateProceedButtonState();
                setTimeout(() => {
                    closeBookingModal();
                    loadScheduleData(weekSelector.value || getTodayUTC().toISOString().split("T")[0]);
                }, 2000);
            } else {
                showModalMessage(result.error || "Erro ao realizar agendamento.", "error");
            }
        } catch (error) {
            console.error("Erro ao submeter agendamento do modal:", error);
            showModalMessage("Falha na comunicação com o servidor. Tente novamente.", "error");
        }
    }

    // --- Event Listeners ---
    if (loadScheduleButton) {
        loadScheduleButton.addEventListener("click", () => {
            const selectedDate = weekSelector.value;
            if (!selectedDate) {
                showScheduleMessage("Por favor, selecione uma data para carregar a semana.", "error");
                return;
            }
            loadScheduleData(selectedDate);
        });
    }

    if (proceedToBookingButton) {
        proceedToBookingButton.addEventListener("click", openBookingModal);
    }

    if (closeModalButton) {
        closeModalButton.addEventListener("click", closeBookingModal);
    }

    window.addEventListener("click", (event) => {
        if (event.target === bookingModal) {
            closeBookingModal();
        }
    });

    if (modalBookingForm) {
        modalBookingForm.addEventListener("submit", handleModalFormSubmit);
    }

    // --- Initializations ---
    async function initializeApp() {
        const todayUTC = getTodayUTC();
        const todayUTCStr = todayUTC.toISOString().split("T")[0];
        if(weekSelector) {
            weekSelector.value = todayUTCStr;
            weekSelector.min = todayUTCStr; // Prevent selecting past dates in the date picker itself
        }
        await fetchAllRooms();
        loadScheduleData(todayUTCStr);
    }

    initializeApp();

});

