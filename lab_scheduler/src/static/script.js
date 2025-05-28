// /home/ubuntu/lab_scheduler/src/static/script.js

document.addEventListener("DOMContentLoaded", () => {
    // DOM Elements
    const weekSelector = document.getElementById("weekSelector");
    const loadScheduleButton = document.getElementById("loadScheduleButton");
    const scheduleTableContainer = document.getElementById("scheduleTableContainer");
    const scheduleMessage = document.getElementById("scheduleMessage");
    const proceedToBookingButton = document.getElementById("proceedToBookingButton");
    const savePdfButton = document.getElementById("savePdfButton"); // PDF Button
    const bookingStatusMessage = document.getElementById("bookingStatusMessage"); // Booking Status Message Area

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
    let currentBookingStatus = {}; // Store booking window status

    // --- Helper Functions for Date Handling (UTC) ---
    function getTodayUTC() {
        const today = new Date();
        return new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate()));
    }

    function parseDateStrToUTC(dateStr) {
        if (!dateStr) return null;
        const [year, month, day] = dateStr.split("-").map(Number);
        return new Date(Date.UTC(year, month - 1, day));
    }

    function formatUTCDate(dateObj, options = { day: "2-digit", month: "2-digit", year: "numeric", timeZone: "UTC" }) {
        if (!dateObj) return "";
        return dateObj.toLocaleDateString("pt-BR", options);
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
        if (type !== "error" && type !== "info") {
             setTimeout(() => {
                scheduleMessage.textContent = "";
                scheduleMessage.className = "message";
            }, 3000);
        }
    }

    function showBookingStatusMessage(status) {
        let message = "Status do Agendamento: ";
        const now = new Date(status.server_time_utc);
        const cutoff = new Date(status.current_week_cutoff);
        const release = new Date(status.next_week_release);

        if (status.current_week_open) {
            message += `Aberto para a semana atual (até ${formatUTCDate(cutoff, {weekday: 'long', hour: '2-digit', minute: '2-digit', timeZone: 'UTC'})}). `;
        } else {
            message += `Fechado para a semana atual (encerrado ${formatUTCDate(cutoff, {weekday: 'long', hour: '2-digit', minute: '2-digit', timeZone: 'UTC'})}). `;
        }

        if (status.next_week_open) {
            const nextCutoff = new Date(status.next_week_release);
            nextCutoff.setUTCDate(nextCutoff.getUTCDate() + (status.current_week_cutoff.getDay() || 7) - (status.next_week_release.getDay() || 7) + 7); // Calculate next cutoff
            message += `Aberto para a próxima semana (até ${formatUTCDate(nextCutoff, {weekday: 'long', hour: '2-digit', minute: '2-digit', timeZone: 'UTC'})}).`;
        } else {
             if (now < release) {
                 message += `Aguardando abertura para a próxima semana (abre ${formatUTCDate(release, {weekday: 'long', hour: '2-digit', minute: '2-digit', timeZone: 'UTC'})}).`;
             } else {
                 message += `Fechado para a próxima semana.`; // Already past next week's cutoff
             }
        }
        bookingStatusMessage.textContent = message;
        bookingStatusMessage.className = "message info";
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

    // --- Booking Status --- 
    async function fetchBookingStatus() {
        try {
            const response = await fetch(`${API_BASE_URL}/booking-status`);
            if (!response.ok) throw new Error(`Erro ao buscar status: ${response.statusText}`);
            currentBookingStatus = await response.json();
            showBookingStatusMessage(currentBookingStatus);
        } catch (error) {
            console.error("Falha ao buscar status do agendamento:", error);
            bookingStatusMessage.textContent = "Não foi possível verificar o status do agendamento.";
            bookingStatusMessage.className = "message error";
        }
    }

    // --- Schedule Logic (Loading and Rendering) ---
    async function loadScheduleData(selectedDateStr) {
        let startDate, endDate;
        const todayUTC = getTodayUTC();

        if (selectedDateStr) {
            const selectedDateObj = parseDateStrToUTC(selectedDateStr);
            const dayOfWeek = selectedDateObj.getUTCDay();
            const diffToMonday = dayOfWeek === 0 ? -6 : 1 - dayOfWeek;
            startDate = new Date(selectedDateObj.setUTCDate(selectedDateObj.getUTCDate() + diffToMonday));
            
            const endOfWeekForCheck = new Date(startDate.valueOf());
            endOfWeekForCheck.setUTCDate(startDate.getUTCDate() + 4);
            // Allow loading past weeks for viewing, but booking will be disabled by other checks
            // if (endOfWeekForCheck < todayUTC && endOfWeekForCheck.toISOString().split("T")[0] !== todayUTC.toISOString().split("T")[0]) {
            //     showScheduleMessage("Não é possível carregar escalas de semanas completamente passadas.", "info");
            //     scheduleTableContainer.innerHTML = "<p>Selecione uma semana atual ou futura.</p>";
            //     return;
            // }
            endDate = new Date(new Date(startDate).setUTCDate(startDate.getUTCDate() + 4));
        } else { // Default to current week
            const todayForLogic = new Date(); 
            const dayOfWeek = todayForLogic.getDay();
            const diffToMonday = dayOfWeek === 0 ? -6 : 1 - dayOfWeek;
            startDate = new Date(todayForLogic.setDate(todayForLogic.getDate() + diffToMonday));
            startDate = parseDateStrToUTC(startDate.toISOString().split("T")[0]);
            endDate = new Date(new Date(startDate).setUTCDate(startDate.getUTCDate() + 4));
        }
        currentWeekStartDate = startDate; 

        const startDateStrAPI = startDate.toISOString().split("T")[0];
        const endDateStrAPI = endDate.toISOString().split("T")[0];
        
        showScheduleMessage("Carregando escala...", "");
        scheduleTableContainer.innerHTML = ""; // Clear previous table
        proceedToBookingButton.disabled = true; // Disable button while loading

        try {
            // Fetch status and bookings in parallel
            await Promise.all([
                fetchBookingStatus(),
                (async () => {
                    const response = await fetch(`${API_BASE_URL}/bookings?start_date=${startDateStrAPI}&end_date=${endDateStrAPI}`);
                    if (!response.ok) throw new Error(`Erro ao buscar agendamentos: ${response.statusText}`);
                    currentFetchedBookings = await response.json();
                })(),
                (async () => {
                     if (allRooms.length === 0) await fetchAllRooms();
                })()
            ]);
            
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
        table.id = "scheduleTable"; // Add ID for PDF generation
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
            th.textContent = `${days[i]} (${formatUTCDate(currentDate)})`;
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
                const isBookingAllowedForSlot = checkBookingWindowFrontend(slotDateUTC);

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
                   " } else if (isPastDate) {
                        cell.textContent = "Indisponível";
                        cell.classList.add("past");"
                    } else if (!isBookingAllowedForSlot) {
                        cell.textContent = "Bloqueado";
                        cell.classList.add("locked"); // New class for slots outside booking window
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

    // Frontend check based on fetched status
    function checkBookingWindowFrontend(slotDateUTC) {
        if (!currentBookingStatus || !currentBookingStatus.current_week_start) {
            console.warn("Booking status not available for frontend check.");
            return false; // Default to not allowed if status unknown
        }
        const now = new Date(currentBookingStatus.server_time_utc);
        const currentWeekStart = parseDateStrToUTC(currentBookingStatus.current_week_start);
        const nextWeekStart = parseDateStrToUTC(currentBookingStatus.next_week_start);
        const cutoff = new Date(currentBookingStatus.current_week_cutoff);
        const release = new Date(currentBookingStatus.next_week_release);
        const nextWeekCutoff = new Date(release);
        nextWeekCutoff.setUTCDate(nextWeekCutoff.getUTCDate() + (cutoff.getUTCDay() || 7) - (release.getUTCDay() || 7) + 7); // Approx next cutoff

        if (slotDateUTC >= currentWeekStart && slotDateUTC < nextWeekStart) { // Slot is in current week
            return now < cutoff;
        } else if (slotDateUTC >= nextWeekStart && slotDateUTC < nextWeekStart + 7*24*60*60*1000) { // Slot is in next week
            return now >= release && now < nextWeekCutoff;
        }
        return false; // Slot is too far in the past or future
    }

    function handleSlotClick(event) {
        const cell = event.currentTarget;
        // Ensure it's clickable (available)
        if (!cell.classList.contains("available")) return;

        const slotDateStr = cell.dataset.date;
        const slotDateUTC = parseDateStrToUTC(slotDateStr);

        // Re-check booking window just in case status changed since render
        if (!checkBookingWindowFrontend(slotDateUTC)) {
            showScheduleMessage("Este horário não está mais disponível para agendamento ou a janela de agendamento fechou.", "error");
            cell.classList.remove("available");
            cell.classList.add("locked");
            cell.textContent = "Bloqueado";
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
        // Disable if no slots selected OR if any selected slot is no longer allowed
        let bookingAllowed = selectedSlots.length > 0;
        if (bookingAllowed) {
            for (const slot of selectedSlots) {
                if (!checkBookingWindowFrontend(parseDateStrToUTC(slot.date))) {
                    bookingAllowed = false;
                    break;
                }
            }
        }
        proceedToBookingButton.disabled = !bookingAllowed;
    }

    // --- Modal Logic ---
    function openBookingModal() {
        if (selectedSlots.length === 0) {
            showScheduleMessage("Nenhum horário selecionado.", "error");
            return;
        }
        // Final check on booking window for all selected slots
        let allSlotsAllowed = true;
        for (const slot of selectedSlots) {
            if (!checkBookingWindowFrontend(parseDateStrToUTC(slot.date))) {
                allSlotsAllowed = false;
                slot.cellRef.classList.remove("selected");
                slot.cellRef.classList.add("locked");
                slot.cellRef.textContent = "Bloqueado";
            }
        }
        // Remove disallowed slots from selection
        selectedSlots = selectedSlots.filter(slot => checkBookingWindowFrontend(parseDateStrToUTC(slot.date)));
        updateProceedButtonState();

        if (!allSlotsAllowed || selectedSlots.length === 0) {
             showScheduleMessage("Um ou mais horários selecionados não estão mais disponíveis devido ao fechamento da janela de agendamento. Verifique a seleção.", "error");
             return;
        }

        selectedSlotsSummaryList.innerHTML = "";
        selectedSlots.forEach(slot => {
            const li = document.createElement("li");
            li.textContent = `${slot.roomName} - ${formatUTCDate(parseDateStrToUTC(slot.date))} - ${slot.period}`;
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
            showModalMessage("Nenhum horário válido selecionado para agendar.", "error");
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
                // Clear selection and update UI immediately
                selectedSlots.forEach(slot => {
                    slot.cellRef.classList.remove("selected", "available");
                    slot.cellRef.classList.add("booked");
                    slot.cellRef.textContent = requestData.user_name;
                    slot.cellRef.removeEventListener("click", handleSlotClick);
                });
                selectedSlots = [];
                updateProceedButtonState();
                setTimeout(() => {
                    closeBookingModal();
                    // Reload schedule to reflect changes and potentially new status
                    loadScheduleData(weekSelector.value || getTodayUTC().toISOString().split("T")[0]); 
                }, 2000);
            } else {
                showModalMessage(result.error || "Erro ao realizar agendamento.", "error");
                // If conflict or other error, reload schedule to show the current state
                if (response.status === 409 || response.status === 400) { 
                     loadScheduleData(weekSelector.value || getTodayUTC().toISOString().split("T")[0]);
                }
            }
        } catch (error) {
            console.error("Erro ao submeter agendamento do modal:", error);
            showModalMessage("Falha na comunicação com o servidor. Tente novamente.", "error");
        }
    }

    // --- PDF Generation --- 
    async function handleSavePdfClick() {
        if (!currentWeekStartDate) {
            showScheduleMessage("Carregue uma escala primeiro para salvar em PDF.", "error");
            return;
        }
        const weekStartDateStr = currentWeekStartDate.toISOString().split("T")[0];
        showScheduleMessage("Gerando PDF...", "info");
        
        // Construct URL for PDF generation endpoint
        const pdfUrl = `${API_BASE_URL}/generate-pdf?week_start_date=${weekStartDateStr}`;
        
        try {
            // Open the URL in a new tab/window, the browser will handle the download
            window.open(pdfUrl, '_blank');
            showScheduleMessage("Download do PDF iniciado.", "success");
        } catch (error) {
            console.error("Erro ao iniciar download do PDF:", error);
            showScheduleMessage("Falha ao gerar PDF.", "error");
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

    if (savePdfButton) {
        savePdfButton.addEventListener("click", handleSavePdfClick);
    }

    // --- Initializations ---
    async function initializeApp() {
        const todayUTC = getTodayUTC();
        const todayUTCStr = todayUTC.toISOString().split("T")[0];
        if(weekSelector) {
            weekSelector.value = todayUTCStr;
            // weekSelector.min = todayUTCStr; // Removing min date to allow viewing past weeks
        }
        await fetchAllRooms(); // Fetch rooms once on load
        loadScheduleData(todayUTCStr); // Load current week and status
    }

    initializeApp();

});
