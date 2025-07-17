document.addEventListener("DOMContentLoaded", () => {
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

    const API_BASE_URL = "/api";
    let allRooms = [], selectedSlots = [], currentWeekStartDate, bookingWindowStatus = null, isAdminMode = false, adminKey = null;

    function showMessage(element, message, type = '') {
        if (element) {
            element.textContent = message;
            element.className = `message ${type}`;
            if (type === 'success' || type === 'info') setTimeout(() => { if (element.textContent === message) element.textContent = ''; }, 4000);
        }
    }

    function getMonday(d) {
        const date = new Date(d), day = date.getUTCDay(), diff = date.getUTCDate() - day + (day === 0 ? -6 : 1);
        return new Date(date.setUTCDate(diff));
    }

    function toYYYYMMDD(date) {
        return date.toISOString().split('T')[0];
    }

    function enterAdminMode() {
        if (isAdminMode) return alert("O modo administrador já está ativo.");
        const key = prompt("Por favor, insira a Chave de Administrador:");
        if (key) {
            adminKey = key;
            isAdminMode = true;
            document.body.insertAdjacentHTML('afterbegin', '<div class="admin-mode-indicator">MODO ADMINISTRADOR ATIVADO</div>');
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

    async function initializeApp() {
        try {
            const response = await fetch(`${API_BASE_URL}/booking-window-status`);
            if (!response.ok) throw new Error(`Falha ao buscar status: ${response.status}`);
            bookingWindowStatus = await response.json();
            if(bookingStatusMessage) bookingStatusMessage.textContent = bookingWindowStatus.general_message;
            const now = new Date(), currentDay = now.getDay(), currentHour = now.getHours();
            let referenceDate = now;
            if ((currentDay === 4 && currentHour >= 18) || currentDay >= 5 || currentDay === 0) {
                const nextWeek = new Date(now);
                nextWeek.setDate(now.getDate() + 7);
                referenceDate = nextWeek;
            }
            await loadScheduleFor(toYYYYMMDD(getMonday(referenceDate)));
        } catch (error) {
            showMessage(scheduleMessage, `Erro ao inicializar: ${error.message}`, "error");
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
        for (let i = 0; i < 5; i++) {
            const currentDate = new Date(weekStartDate);
            currentDate.setUTCDate(weekStartDate.getUTCDate() + i);
            datesOfWeek.push(toYYYYMMDD(currentDate));
            const th = document.createElement("th");
            th.colSpan = 2;
            th.textContent = `${["Segunda", "Terça", "Quarta", "Quinta", "Sexta"][i]} (${currentDate.toLocaleDateString("pt-BR", {day:"2-digit", month:"2-digit", timeZone: "UTC"})})`;
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
        const slotData = { roomId: parseInt(cell.dataset.roomId), roomName: cell.dataset.roomName, date: cell.
