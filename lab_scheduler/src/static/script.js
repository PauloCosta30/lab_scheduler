document.addEventListener("DOMContentLoaded", () => {
    // --- Elementos DOM ---
    const scheduleTableContainer = document.getElementById("scheduleTableContainer"),
        scheduleMessage = document.getElementById("scheduleMessage"),
        proceedToBookingButton = document.getElementById("proceedToBookingButton"),
        generatePdfButton = document.getElementById("generatePdfButton"),
        weekSelector = document.getElementById("weekSelector"),
        loadScheduleButton = document.getElementById("loadScheduleButton"),
        prevWeekButton = document.getElementById("prevWeekButton"),
        nextWeekButton = document.getElementById("nextWeekButton"),
        bookingStatusMessage = document.getElementById("bookingStatusMessage"),
        bookingModal = document.getElementById("bookingModal"),
        closeModalButton = document.querySelector(".close-button"),
        modalBookingForm = document.getElementById("modalBookingForm"),
        selectedSlotsSummaryList = document.querySelector("#selectedSlotsSummary ul"),
        modalFormMessage = document.getElementById("modalFormMessage"),
        adminLoginLink = document.getElementById("adminLoginLink");

    // --- Variáveis Globais ---
    const API_BASE_URL = "/api";
    let allRooms = [], selectedSlots = [], currentWeekStartDate, bookingWindowStatus = null, isAdminMode = false, adminKey = null;

    // --- Funções Helper ---
    function showMessage(element, message, type = '') {
        if (element) {
            element.textContent = message;
            element.className = `message ${type}`;
            if (type === 'success' || type === 'info') {
                setTimeout(() => {
                    if (element.textContent === message) {
                        element.textContent = '';
                        element.className = 'message';
                    }
                }, 4000);
            }
        }
    }

    function getMonday(d) {
        const date = new Date(d);
        const day = date.getUTCDay();
        const diff = date.getUTCDate() - day + (day === 0 ? -6 : 1);
        return new Date(date.setUTCDate(diff));
    }

    function toYYYYMMDD(date) {
        return date.toISOString().split('T')[0];
    }

    // --- Lógica de Admin ---
    function enterAdminMode() {
        if (isAdminMode) return alert("O modo administrador já está ativo.");
        const key = prompt("Por favor, insira a Chave de Administrador:");
        if (key) {
            adminKey = key;
            isAdminMode = true;
            const indicator = document.createElement('div');
            indicator.className = 'admin-mode-indicator';
            indicator.textContent = 'MODO ADMINISTRADOR ATIVADO';
            document.body.insertAdjacentElement('afterbegin', indicator);
            if (currentWeekStartDate) loadScheduleFor(toYYYYMMDD(currentWeekStartDate));
        }
    }

    async function handleAdminCellClick(cell) {
        const { roomName, date, period, roomId } = cell.dataset;
        const currentHolder = cell.classList.contains('booked') ? cell.textContent.trim() : "";
        const newUserName = prompt(`Editando: ${roomName} - ${date} - ${period}\n\nUsuário Atual: "${currentHolder}"\n\nNovo nome (deixe em branco para remover):`, currentHolder);
        if (newUserName === null) return;
        showMessage(scheduleMessage, "Salvando alteração...", "info");
        try {
            const response = await fetch(`${API_BASE_URL}/admin/booking`, {
                method: "POST",
                headers: { "Content-Type": "application/json", "X-Admin-Key": adminKey },
                body: JSON.stringify({ room_id: parseInt(roomId), booking_date: date, period, user_name: newUserName.trim() })
            });
            const result = await response.json();
            if (!response.ok) throw new Error(result.error || `Erro ${response.status}`);
            showMessage(scheduleMessage, result.message, "success");
            if (newUserName.trim()) {
                cell.textContent = newUserName.trim();
                cell.className = 'schedule-cell booked admin-editable';
            } else {
                cell.textContent = "Disponível";
                cell.className = 'schedule-cell available admin-editable';
            }
        } catch (error) {
            showMessage(scheduleMessage, `Falha na edição: ${error.message}`, "error");
        }
    }

    // --- Lógica de Carregamento ---
    async function initializeApp() {
        try {
            const response = await fetch(`${API_BASE_URL}/booking-window-status`);
            if (!response.ok) throw new Error(`Falha ao buscar status: ${response.status}`);
            bookingWindowStatus = await response.json();
            if(bookingStatusMessage) bookingStatusMessage.textContent = bookingWindowStatus.general_message;
            
            const now = new Date();
            let referenceDate = now;
            const currentDay = now.getDay();
            const currentHour = now.getHours();
            
            if ((currentDay === 4 && currentHour >= 18) || currentDay >= 5 || currentDay === 0) {
                const nextWeek = new Date(now);
                nextWeek.setDate(now.getDate() + 7);
                referenceDate = nextWeek;
            }
            
            await loadScheduleFor(toYYYYMMDD(getMonday(referenceDate)));
        } catch (error) {
            showMessage(scheduleMessage, `Erro ao inicializar: ${error.message}`, "error");
            if(bookingStatusMessage) bookingStatusMessage.textContent = "Erro de conexão com o servidor.";
        }
    }

    async function loadScheduleFor(startDateStr) {
        showMessage(scheduleMessage, "Carregando escala...", "");
        try {
            currentWeekStartDate = new Date(`${startDateStr}T12:00:00Z`);
            if(weekSelector) weekSelector.value = startDateStr;
            
            const endDate = new Date(currentWeekStartDate);
            endDate.setUTCDate(currentWeekStartDate.getUTCDate() + 4);
            
            if (allRooms.length === 0) {
                const roomsResponse = await fetch(`${API_BASE_URL}/rooms`);
                if (!roomsResponse.ok) throw new Error("Falha ao carregar salas.");
                allRooms = await roomsResponse.json();
            }
            
            const bookingsResponse = await fetch(`${API_BASE_URL}/bookings?start_date=${startDateStr}&end_date=${toYYYYMMDD(endDate)}`);
            if (!bookingsResponse.ok) throw new Error("Falha ao carregar agendamentos.");
            const bookings = await bookingsResponse.json();
            
            renderScheduleTable(bookings, allRooms, currentWeekStartDate);
            showMessage(scheduleMessage, "Escala carregada.", "success");
        } catch (error) {
            showMessage(scheduleMessage, `Erro ao carregar escala: ${error.message}`, "error");
            if(scheduleTableContainer) scheduleTableContainer.innerHTML = "";
        }
    }

    function renderScheduleTable(bookings, rooms, weekStartDate) {
        if (!scheduleTableContainer || !rooms || !weekStartDate) return;
        scheduleTableContainer.innerHTML = "";
        selectedSlots = [];
        updateButtonStates();
        
        const table = document.createElement("table"), thead = document.createElement("thead"), tbody = document.createElement("tbody");
        table.className = "schedule-table";
        
        const headerRow = document.createElement("tr");
        headerRow.innerHTML = "<th>Sala</th>";
        const datesOfWeek = [];
        const days = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta"];
        
        for (let i = 0; i < 5; i++) {
            const currentDate = new Date(weekStartDate);
            currentDate.setUTCDate(weekStartDate.getUTCDate() + i);
            datesOfWeek.push(toYYYYMMDD(currentDate));
            const th = document.createElement("th");
            th.colSpan = 2;
            th.textContent = `${days[i]} (${currentDate.toLocaleDateString("pt-BR", {day:"2-digit", month:"2-digit", timeZone: "UTC"})})`;
            headerRow.appendChild(th);
        }
        thead.appendChild(headerRow);
        
        const subHeaderRow = document.createElement("tr");
        subHeaderRow.innerHTML = "<td></td>";
        for (let i = 0; i < 5; i++) subHeaderRow.innerHTML += "<th>Manhã</th><th>Tarde</th>";
        thead.appendChild(subHeaderRow);
        table.appendChild(thead);
        
        rooms.forEach(room => {
            const row = document.createElement("tr");
            row.innerHTML = `<td class="room-name">${room.name}</td>`;
            datesOfWeek.forEach(dateStr => {
                ["Manhã", "Tarde"].forEach(period => {
                    const cell = document.createElement("td");
                    cell.className = "schedule-cell";
                    cell.dataset.roomId = room.id;
                    cell.dataset.roomName = room.name;
                    cell.dataset.date = dateStr;
                    cell.dataset.period = period;
                    const booking = bookings.find(b => b.room_id === room.id && b.booking_date === dateStr && b.period === period);
                    
                    if (isAdminMode) {
                        cell.classList.add("admin-editable");
                        cell.addEventListener("click", () => handleAdminCellClick(cell));
                        cell.textContent = booking ? booking.user_name : "Disponível";
                        cell.classList.add(booking ? "booked" : "available");
                    } else {
                        if (booking) {
                            cell.textContent = booking.user_name;
                            cell.classList.add("booked");
                        } else {
                            if (checkIfBookingAllowed(dateStr)) {
                                cell.textContent = "Disponível";
                                cell.classList.add("available");
                                cell.addEventListener("click", handleSlotClick);
                            } else {
                                cell.textContent = "Fechado";
                                cell.classList.add("closed");
                            }
                        }
                    }
                    row.appendChild(cell);
                });
            });
            tbody.appendChild(row);
        });
        
        table.appendChild(tbody);
        scheduleTableContainer.appendChild(table);
    }

    function checkIfBookingAllowed(dateStr) {
        if (!bookingWindowStatus) return false;
        const mondayOfSlotWeek = getMonday(new Date(`${dateStr}T12:00:00Z`));
        const mondayOfCurrentWeek = getMonday(new Date());
        if (mondayOfSlotWeek.toISOString().split('T')[0] === mondayOfCurrentWeek.toISOString().split('T')[0]) {
            return bookingWindowStatus.current_week.open;
        }
        return bookingWindowStatus.next_week.open;
    }

    function handleSlotClick(event) {
        const cell = event.currentTarget;
        const slotData = {
            roomId: parseInt(cell.dataset.roomId),
            roomName: cell.dataset.roomName,
            date: cell.dataset.date,
            period: cell.dataset.period,
            cellRef: cell
        };
        const existingIndex = selectedSlots.findIndex(s => s.roomId === slotData.roomId && s.date === slotData.date && s.period === slotData.period);
        if (existingIndex > -1) {
            selectedSlots.splice(existingIndex, 1);
            cell.classList.remove("selected");
            cell.textContent = "Disponível";
        } else {
            selectedSlots.push(slotData);
            cell.classList.add("selected");
            cell.textContent = "Selecionado";
        }
        updateButtonStates();
    }

    function updateButtonStates() {
        if (proceedToBookingButton) proceedToBookingButton.disabled = false;
        if (generatePdfButton) generatePdfButton.disabled = !currentWeekStartDate;
    }

    // --- Event Listeners ---
    if (adminLoginLink) adminLoginLink.addEventListener("click", (e) => { e.preventDefault(); enterAdminMode(); });
    if (loadScheduleButton) loadScheduleButton.addEventListener("click", () => { if (weekSelector.value) loadScheduleFor(toYYYYMMDD(getMonday(new Date(`${weekSelector.value}T12:00:00Z`)))); });
    if (prevWeekButton) prevWeekButton.addEventListener("click", () => { if (currentWeekStartDate) { const d = new Date(currentWeekStartDate); d.setUTCDate(d.getUTCDate() - 7); loadScheduleFor(toYYYYMMDD(d)); } });
    if (nextWeekButton) nextWeekButton.addEventListener("click", () => { if (currentWeekStartDate) { const d = new Date(currentWeekStartDate); d.setUTCDate(d.getUTCDate() + 7); loadScheduleFor(toYYYYMMDD(d)); } });
    if (generatePdfButton) generatePdfButton.addEventListener("click", generatePdf);
    if (closeModalButton) closeModalButton.addEventListener("click", () => bookingModal.style.display = "none");
    window.addEventListener("click", (event) => { if (event.target === bookingModal) bookingModal.style.display = "none"; });
    if (modalBookingForm) modalBookingForm.addEventListener("submit", (e) => { e.preventDefault(); createBooking(new FormData(modalBookingForm)); });
    if (proceedToBookingButton) proceedToBookingButton.addEventListener("click", () => { updateSelectedSlotsSummary(); bookingModal.style.display = "block"; });

    // --- Inicialização ---
    initializeApp();
});

// Funções de PDF e createBooking não mostradas para brevidade, mas estão no código completo
async function generatePdf() { /* ... */ }
async function createBooking(formData) { /* ... */ }
function updateSelectedSlotsSummary() { /* ... */ }
