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
    let currentWeekStartDate; // Monday of the currently displayed week
    let currentBookingStatus = {}; // Store booking window status

    // --- Helper Functions for Date Handling (UTC) ---
    function getTodayUTC() {
        const today = new Date();
        return new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate()));
    }

    function parseDateStrToUTC(dateStr) {
        if (!dateStr) return null;
        const [year, month, day] = dateStr.split("-").map(Number);
        // Month is 0-indexed in JS Date
        return new Date(Date.UTC(year, month - 1, day));
    }

    function formatUTCDate(dateObj, options = { day: "2-digit", month: "2-digit", year: "numeric", timeZone: "UTC" }) {
        if (!dateObj) return "";
        // Use toLocaleDateString for formatting
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

    // Function to display booking status with local time hints - CORRIGIDO
    function showBookingStatusMessage(status) {
        let message = "Status do Agendamento: ";
        const now = new Date(status.server_time_utc);
        const cutoff = new Date(status.current_week_cutoff); // Wednesday 21:00 UTC
        const release = new Date(status.next_week_release); // Thursday 02:59 UTC

        // Hardcoded display times (local Brazil Time)
        const displayCutoffTime = "18:00";
        const displayReleaseTime = "23:59";

        // Simplificado para mostrar apenas o status atual sem informações confusas
        if (status.current_week_open) {
            message += `Aberto para a semana atual (até quarta-feira, ${displayCutoffTime}).`;
        } else if (status.next_week_open) {
            message += `Aberto para a próxima semana (até quarta-feira, ${displayCutoffTime}).`;
        } else if (now < release) {
            message += `Fechado para a semana atual. Aguardando abertura para a próxima semana (abre quinta-feira, ${displayReleaseTime}).`;
        } else {
            message += `Fechado para agendamentos.`;
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
            return currentBookingStatus; // Return status for default week logic
        } catch (error) {
            console.error("Falha ao buscar status do agendamento:", error);
            bookingStatusMessage.textContent = "Não foi possível verificar o status do agendamento.";
            bookingStatusMessage.className = "message error";
            return null; // Return null on error
        }
    }

    // --- Schedule Logic (Loading and Rendering) ---
    async function loadScheduleData(selectedDateStr) {
        let startDate, endDate;
        let fetchedStatus = currentBookingStatus; // Use cached status first

        // Always fetch latest status before deciding which week to load by default
        if (!selectedDateStr) {
            fetchedStatus = await fetchBookingStatus();
            if (!fetchedStatus) {
                 showScheduleMessage("Erro ao obter status para carregar semana padrão.", "error");
                 return;
            }
        }

        if (selectedDateStr) {
            // If a date is selected, load that specific week (Mon-Fri)
            const selectedDateObj = parseDateStrToUTC(selectedDateStr);
            const dayOfWeek = selectedDateObj.getUTCDay(); // 0=Sun, 1=Mon, ..., 6=Sat
            
            // CORREÇÃO: Garantir que a semana sempre comece na segunda-feira
            // Se for domingo (0), vá para a segunda-feira seguinte (+1)
            // Se for outro dia, vá para a segunda-feira da mesma semana
            let diffToMonday;
            if (dayOfWeek === 0) {
                diffToMonday = 1; // Domingo -> Segunda (próxima)
            } else {
                diffToMonday = 1 - dayOfWeek; // Outros dias -> Segunda (mesma semana)
            }
            
            startDate = new Date(Date.UTC(selectedDateObj.getUTCFullYear(), selectedDateObj.getUTCMonth(), selectedDateObj.getUTCDate() + diffToMonday));
        } else {
            // Default week logic: Load current or next week based on release time
            const now = new Date(fetchedStatus.server_time_utc);
            const release = new Date(fetchedStatus.next_week_release); // Thursday 02:59 UTC
            const todayForLogic = new Date(now); // Use server time for consistency
            const dayOfWeek = todayForLogic.getUTCDay();
            
            // CORREÇÃO: Garantir que a semana sempre comece na segunda-feira
            // Se for domingo (0), vá para a segunda-feira seguinte (+1)
            // Se for outro dia, vá para a segunda-feira da mesma semana
            let diffToMonday;
            if (dayOfWeek === 0) {
                diffToMonday = 1; // Domingo -> Segunda (próxima)
            } else {
                diffToMonday = 1 - dayOfWeek; // Outros dias -> Segunda (mesma semana)
            }
            
            const currentMonday = new Date(Date.UTC(todayForLogic.getUTCFullYear(), todayForLogic.getUTCMonth(), todayForLogic.getUTCDate() + diffToMonday));

            if (now >= release) {
                // If past release time, default to NEXT week
                startDate = new Date(Date.UTC(currentMonday.getUTCFullYear(), currentMonday.getUTCMonth(), currentMonday.getUTCDate() + 7));
            } else {
                // Otherwise, default to CURRENT week
                startDate = currentMonday;
            }
            // Update the week selector to reflect the loaded week
            weekSelector.value = startDate.toISOString().split("T")[0];
        }

        // Calculate end date (Friday of the week)
        endDate = new Date(Date.UTC(startDate.getUTCFullYear(), startDate.getUTCMonth(), startDate.getUTCDate() + 4)); // +4 para sexta-feira
        currentWeekStartDate = startDate; // Store the Monday of the displayed week

        const startDateStrAPI = startDate.toISOString().split("T")[0];
        const endDateStrAPI = endDate.toISOString().split("T")[0];
        
        showScheduleMessage("Carregando escala...", "");
        scheduleTableContainer.innerHTML = ""; // Clear previous table
        proceedToBookingButton.disabled = true; // Disable button while loading

        try {
            // Fetch bookings and ensure rooms are loaded
            // Status might already be fetched if loading default week
            const promises = [
                (async () => {
                    const response = await fetch(`${API_BASE_URL}/bookings?start_date=${startDateStrAPI}&end_date=${endDateStrAPI}`);
                    if (!response.ok) throw new Error(`Erro ao buscar agendamentos: ${response.statusText}`);
                    currentFetchedBookings = await response.json();
                })(),
                (async () => {
                     if (allRooms.length === 0) await fetchAllRooms();
                })()
            ];
            // Only fetch status again if it wasn't fetched for default week logic
            if (selectedDateStr) {
                 promises.push(fetchBookingStatus());
            }
            
            await Promise.all(promises);
            
            renderScheduleTable(currentFetchedBookings, allRooms, currentWeekStartDate);
            showScheduleMessage("Escala carregada.", "success");
        } catch (error) {
            console.error("Falha ao carregar escala:", error);
            showScheduleMessage("Não foi possível carregar a escala.", "error");
            scheduleTableContainer.innerHTML = "<p>Erro ao carregar escala.</p>";
        }
    }

    // Renders the schedule table for 5 days (Mon-Fri)
    
// Correção no script para garantir que domingo nunca seja exibido na tabela, mesmo que venha do backend
// Trecho modificado: renderScheduleTable()

function renderScheduleTable(bookings, roomsData, weekStartDateObj) {
    scheduleTableContainer.innerHTML = "";
    selectedSlots = [];
    updateProceedButtonState();

    const table = document.createElement("table");
    table.id = "scheduleTable";
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
        th.textContent = `${days[i]} (${formatUTCDate(currentDate, {day: "2-digit", month: "2-digit"})})`;
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

    roomsData.sort((a, b) => a.id - b.id).forEach(room => {
        const row = document.createElement("tr");
        const roomCell = document.createElement("td");
        roomCell.textContent = room.name;
        row.appendChild(roomCell);

        datesOfWeek.forEach(dateStr => {
            const slotDateUTC = parseDateStrToUTC(dateStr);
            const dayOfWeek = slotDateUTC.getUTCDay();

            // Ignorar se for domingo (0) ou sábado (6)
            if (dayOfWeek === 0 || dayOfWeek === 6) return;

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
                } else if (!isBookingAllowedForSlot) {
                    cell.textContent = "Bloqueado";
                    cell.classList.add("locked");
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
    // Frontend check based on fetched status (uses UTC dates)
    function checkBookingWindowFrontend(slotDateUTC) {
        if (!currentBookingStatus || !currentBookingStatus.current_week_start) {
            console.warn("Booking status not available for frontend check.");
            return false; // Default to not allowed if status unknown
        }
        const now = new Date(currentBookingStatus.server_time_utc);
        const currentWeekStart = parseDateStrToUTC(currentBookingStatus.current_week_start);
        const nextWeekStart = parseDateStrToUTC(currentBookingStatus.next_week_start);
        const currentWeekEnd = parseDateStrToUTC(currentBookingStatus.current_week_end); // Friday
        const nextWeekEnd = parseDateStrToUTC(currentBookingStatus.next_week_end); // Friday
        
        const cutoffCurrent = new Date(currentBookingStatus.current_week_cutoff);
        const releaseNext = new Date(currentBookingStatus.next_week_release);
        
        // Calculate cutoff for the next week (Wednesday 21:00 UTC of next week)
        const cutoffNext = new Date(nextWeekStart);
        cutoffNext.setUTCDate(nextWeekStart.getUTCDate() + 2); // Go to Wednesday
        cutoffNext.setUTCHours(21, 0, 0, 0); // Set time to 21:00 UTC

        // Check if the slot date falls within the current week (Mon-Fri)
        if (slotDateUTC >= currentWeekStart && slotDateUTC <= currentWeekEnd) {
            // Also check if it's a weekend (shouldn't happen with backend block, but good practice)
            if (slotDateUTC.getUTCDay() === 0 || slotDateUTC.getUTCDay() === 6) return false;
            return now < cutoffCurrent; // Allowed only if before current week's cutoff
        }
        // Check if the slot date falls within the next week (Mon-Fri)
        else if (slotDateUTC >= nextWeekStart && slotDateUTC <= nextWeekEnd) {
            // Also check if it's a weekend
            if (slotDateUTC.getUTCDay() === 0 || slotDateUTC.getUTCDay() === 6) return false;
            // Allowed only if after release time AND before next week's cutoff
            return now >= releaseNext && now < cutoffNext;
        }
        // Allow past dates based on backend logic (if user configured it)
        else if (slotDateUTC < currentWeekStart) {
            // Check if it's a weekend
            if (slotDateUTC.getUTCDay() === 0 || slotDateUTC.getUTCDay() === 6) return false;
            // Assume backend handles validation for past dates
            return true; // Allow interaction, backend will validate
        }
        
        return false; // Slot is too far in the future or invalid
    }

    function handleSlotClick(event) {
        const cell = event.currentTarget;
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
            // Check max selection limit (e.g., 3 per request)
            if (selectedSlots.length >= 3) {
                 showScheduleMessage("Você pode selecionar no máximo 3 horários por vez.", "info");
                 return;
            }
            selectedSlots.push(slotData);
            cell.classList.add("selected");
            cell.textContent = "Selecionado";
        }
        updateProceedButtonState();
    }

    function updateProceedButtonState() {
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
            li.textContent = `${slot.roomName} - ${formatUTCDate(parseDateStrToUTC(slot.date), {day: "2-digit", month: "2-digit"})} - ${slot.period}`;
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
            if (response.ok) {
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
                    loadScheduleData(weekSelector.value || null); // Reload current or default week
                }, 2000);
            } else {
                showModalMessage(result.error || "Erro ao realizar agendamento.", "error");
                // If conflict or other error, reload schedule to show the current state
                if (response.status === 409 || response.status === 400) { 
                     loadScheduleData(weekSelector.value || null);
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
            window.open(pdfUrl, "_blank");
            showScheduleMessage("O download do PDF deve iniciar em breve.", "success");
        } catch (error) {
            console.error("Erro ao tentar gerar PDF:", error);
            showScheduleMessage("Falha ao iniciar geração do PDF.", "error");
        }
    }

    // --- Initialization ---
    function initialize() {
        // Event Listeners
        loadScheduleButton.addEventListener("click", () => loadScheduleData(weekSelector.value));
        proceedToBookingButton.addEventListener("click", openBookingModal);
        savePdfButton.addEventListener("click", handleSavePdfClick); // PDF button listener
        closeModalButton.addEventListener("click", closeBookingModal);
        modalBookingForm.addEventListener("submit", handleModalFormSubmit);
        window.addEventListener("click", (event) => {
            if (event.target === bookingModal) {
                closeBookingModal();
            }
        });

        // Initial Load (will now load current or next week based on status)
        loadScheduleData(null);
    }

    initialize();
});
