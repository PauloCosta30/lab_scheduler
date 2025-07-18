document.addEventListener("DOMContentLoaded", () => {
    // --- Elementos DOM ---
    const dom = {
        scheduleTableContainer: document.getElementById("scheduleTableContainer"),
        scheduleMessage: document.getElementById("scheduleMessage"),
        proceedToBookingButton: document.getElementById("proceedToBookingButton"),
        generatePdfButton: document.getElementById("generatePdfButton"),
        weekSelector: document.getElementById("weekSelector"),
        loadScheduleButton: document.getElementById("loadScheduleButton"),
        prevWeekButton: document.getElementById("prevWeekButton"),
        nextWeekButton: document.getElementById("nextWeekButton"),
        bookingStatusMessage: document.getElementById("bookingStatusMessage"),
        bookingModal: document.getElementById("bookingModal"),
        closeModalButton: document.querySelector(".close-button"),
        modalBookingForm: document.getElementById("modalBookingForm"),
        selectedSlotsSummaryList: document.querySelector("#selectedSlotsSummary ul"),
        modalFormMessage: document.getElementById("modalFormMessage"),
        adminLoginLink: document.getElementById("adminLoginLink")
    };

    // --- Variáveis Globais ---
    const API_BASE_URL = "/api";
    let allRooms = [], selectedSlots = [], currentWeekStartDate, bookingWindowStatus = null, isAdminMode = false, adminKey = null;

    // --- Funções Helper ---
    const showMessage = (element, message, type = '') => {
        if (element) {
            element.textContent = message;
            element.className = `message ${type}`;
            if (type === 'success' || type === 'info') {
                setTimeout(() => { if (element.textContent === message) element.textContent = ''; }, 4000);
            }
        }
    };
    const getMonday = d => {
        const date = new Date(d);
        const day = date.getUTCDay();
        const diff = date.getUTCDate() - day + (day === 0 ? -6 : 1);
        return new Date(date.setUTCDate(diff));
    };
    const toYYYYMMDD = date => date.toISOString().split('T')[0];

    // --- Objeto Principal da Aplicação ---
    const app = {
        init() {
            this.addEventListeners();
            this.initializeApp();
        },

        addEventListeners() {
            if (dom.adminLoginLink) dom.adminLoginLink.addEventListener("click", e => { e.preventDefault(); this.enterAdminMode(); });
            if (dom.loadScheduleButton) dom.loadScheduleButton.addEventListener("click", () => { if (dom.weekSelector.value) this.loadScheduleFor(toYYYYMMDD(getMonday(new Date(`${dom.weekSelector.value}T12:00:00Z`)))); });
            if (dom.prevWeekButton) dom.prevWeekButton.addEventListener("click", () => { if (currentWeekStartDate) { const d = new Date(currentWeekStartDate); d.setUTCDate(d.getUTCDate() - 7); this.loadScheduleFor(toYYYYMMDD(d)); } });
            if (dom.nextWeekButton) dom.nextWeekButton.addEventListener("click", () => { if (currentWeekStartDate) { const d = new Date(currentWeekStartDate); d.setUTCDate(d.getUTCDate() + 7); this.loadScheduleFor(toYYYYMMDD(d)); } });
            if (dom.closeModalButton) dom.closeModalButton.addEventListener("click", () => dom.bookingModal.style.display = "none");
            window.addEventListener("click", event => { if (event.target === dom.bookingModal) dom.bookingModal.style.display = "none"; });
            if (dom.modalBookingForm) dom.modalBookingForm.addEventListener("submit", e => { e.preventDefault(); this.createBooking(new FormData(dom.modalBookingForm)); });
            if (dom.proceedToBookingButton) dom.proceedToBookingButton.addEventListener("click", () => { this.updateSelectedSlotsSummary(); dom.bookingModal.style.display = "block"; });
            if (dom.generatePdfButton) dom.generatePdfButton.addEventListener("click", () => this.generatePdf());
        },

        async initializeApp() {
            try {
                const response = await fetch(`${API_BASE_URL}/booking-window-status`);
                if (!response.ok) throw new Error(`Falha ao buscar status: ${response.status}`);
                bookingWindowStatus = await response.json();
                if (dom.bookingStatusMessage) dom.bookingStatusMessage.textContent = bookingWindowStatus.general_message;
                
                const now = new Date();
                let referenceDate = now;
                const currentDay = now.getUTCDay();
                const currentHour = now.getHours();
                
                if ((currentDay === 4 && currentHour >= 18) || currentDay === 5 || currentDay === 6 || currentDay === 0) {
                    const nextWeek = new Date(now);
                    nextWeek.setDate(now.getDate() + 7);
                    referenceDate = nextWeek;
                }
                
                await this.loadScheduleFor(toYYYYMMDD(getMonday(referenceDate)));
            } catch (error) {
                showMessage(dom.scheduleMessage, `Erro ao inicializar: ${error.message}`, "error");
                if (dom.bookingStatusMessage) dom.bookingStatusMessage.textContent = "Erro de conexão com o servidor.";
            }
        },

        async loadScheduleFor(startDateStr) {
            showMessage(dom.scheduleMessage, "Carregando escala...", "info");
            try {
                currentWeekStartDate = new Date(`${startDateStr}T12:00:00Z`);
                if (dom.weekSelector) dom.weekSelector.value = startDateStr;
                
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
                
                this.renderScheduleTable(bookings, allRooms, currentWeekStartDate);
                showMessage(dom.scheduleMessage, "Escala carregada.", "success");
            } catch (error) {
                showMessage(dom.scheduleMessage, `Erro ao carregar escala: ${error.message}`, "error");
                if (dom.scheduleTableContainer) dom.scheduleTableContainer.innerHTML = "";
            }
        },

        renderScheduleTable(bookings, rooms, weekStartDate) {
            if (!dom.scheduleTableContainer || !rooms || !weekStartDate) return;
            dom.scheduleTableContainer.innerHTML = "";
            selectedSlots = [];
            this.updateButtonStates();
            
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
                            cell.addEventListener("click", () => this.handleAdminCellClick(cell));
                            cell.textContent = booking ? booking.user_name : "Disponível";
                            cell.classList.add(booking ? "booked" : "available");
                        } else {
                            if (booking) {
                                cell.textContent = booking.user_name;
                                cell.classList.add("booked");
                            } else {
                                if (this.checkIfBookingAllowed(dateStr)) {
                                    cell.textContent = "Disponível";
                                    cell.classList.add("available");
                                    cell.addEventListener("click", e => this.handleSlotClick(e));
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
            dom.scheduleTableContainer.appendChild(table);
        },

        checkIfBookingAllowed(dateStr) {
            if (!bookingWindowStatus) return false;
            const mondayOfSlotWeek = getMonday(new Date(`${dateStr}T12:00:00Z`));
            const mondayOfCurrentWeek = getMonday(new Date());
            if (toYYYYMMDD(mondayOfSlotWeek) === toYYYYMMDD(mondayOfCurrentWeek)) {
                return bookingWindowStatus.current_week.open;
            }
            return bookingWindowStatus.next_week.open;
        },

        updateButtonStates() {
            if (dom.proceedToBookingButton) dom.proceedToBookingButton.disabled = false;
            if (dom.generatePdfButton) dom.generatePdfButton.disabled = !currentWeekStartDate;
        },

        handleSlotClick(event) {
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
            this.updateButtonStates();
        },

        updateSelectedSlotsSummary() {
            if (!dom.selectedSlotsSummaryList) return;
            dom.selectedSlotsSummaryList.innerHTML = "";
            if (selectedSlots.length === 0) {
                dom.selectedSlotsSummaryList.innerHTML = "<li><em>Nenhum horário selecionado - Agendamento somente observação</em></li>";
                return;
            }
            selectedSlots.forEach(slot => {
                const li = document.createElement("li");
                li.textContent = `${slot.roomName} - ${slot.date} - ${slot.period}`;
                dom.selectedSlotsSummaryList.appendChild(li);
            });
        },

        async createBooking(formData) {
            showMessage(dom.modalFormMessage, "Enviando agendamento...", "info");
            const bookingData = {
                user_name: formData.get("userName"),
                user_email: formData.get("userEmail"),
                coordinator_name: formData.get("coordinatorName"),
                observation: formData.get("observation"),
                slots: selectedSlots.map(s => ({ room_id: s.roomId, booking_date: s.date, period: s.period }))
            };
            try {
                const response = await fetch(`${API_BASE_URL}/bookings`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(bookingData)
                });
                const result = await response.json();
                if (!response.ok) throw new Error(result.error || `Erro ${response.status}`);
                
                showMessage(dom.modalFormMessage, result.message, "success");
                dom.modalBookingForm.reset(); // Limpa o formulário

                setTimeout(() => {
                    dom.bookingModal.style.display = "none";
                    this.loadScheduleFor(toYYYYMMDD(currentWeekStartDate));
                }, 2000);
            } catch (error) {
                showMessage(dom.modalFormMessage, `Falha no agendamento: ${error.message}`, "error");
            }
        },

        async generatePdf() {
            if (!currentWeekStartDate) {
                showMessage(dom.scheduleMessage, "Carregue uma escala primeiro.", "error");
                return;
            }
            showMessage(dom.scheduleMessage, "Gerando PDF...", "info");
            const startDate = toYYYYMMDD(currentWeekStartDate);
            const endDate = toYYYYMMDD(new Date(currentWeekStartDate.getTime() + 4 * 24 * 60 * 60 * 1000));
            try {
                const response = await fetch(`${API_BASE_URL}/generate-pdf?start_date=${startDate}&end_date=${endDate}`);
                if (!response.ok) throw new Error(`Erro do servidor: ${response.statusText}`);
                const blob = await response.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement("a");
                a.style.display = "none";
                a.href = url;
                a.download = `escala_agendamentos_${startDate}_a_${endDate}.pdf`;
                document.body.appendChild(a);
                a.click();
                window.URL.revokeObjectURL(url);
                document.body.removeChild(a);
                showMessage(dom.scheduleMessage, "PDF gerado com sucesso!", "success");
            } catch (error) {
                showMessage(dom.scheduleMessage, `Falha ao gerar PDF: ${error.message}`, "error");
            }
        },

        enterAdminMode() {
            if (isAdminMode) return;
            const key = prompt("Por favor, insira a Chave de Administrador:");
            if (key) {
                adminKey = key;
                isAdminMode = true;
                const indicator = document.createElement('div');
                indicator.className = 'admin-mode-indicator';
                indicator.textContent = 'MODO ADMINISTRADOR ATIVADO';
                document.body.insertAdjacentElement('afterbegin', indicator);
                if (currentWeekStartDate) this.loadScheduleFor(toYYYYMMDD(currentWeekStartDate));
            }
        },

        async handleAdminCellClick(cell) {
            const { roomName, date, period, roomId } = cell.dataset;
            const currentHolder = cell.classList.contains('booked') ? cell.textContent.trim() : "";
            const newUserName = prompt(`Editando: ${roomName} - ${date} - ${period}\n\nUsuário Atual: "${currentHolder}"\n\nNovo nome (deixe em branco para remover):`, currentHolder);
            if (newUserName === null) return;
            showMessage(dom.scheduleMessage, "Salvando alteração...", "info");
            try {
                const response = await fetch(`${API_BASE_URL}/admin/booking`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json", "X-Admin-Key": adminKey },
                    body: JSON.stringify({ room_id: parseInt(roomId), booking_date: date, period, user_name: newUserName.trim() })
                });
                const result = await response.json();
                if (!response.ok) throw new Error(result.error || `Erro ${response.status}`);
                showMessage(dom.scheduleMessage, result.message, "success");
                if (newUserName.trim()) {
                    cell.textContent = newUserName.trim();
                    cell.className = 'schedule-cell booked admin-editable';
                } else {
                    cell.textContent = "Disponível";
                    cell.className = 'schedule-cell available admin-editable';
                }
            } catch (error) {
                showMessage(dom.scheduleMessage, `Falha na edição: ${error.message}`, "error");
            }
        }
    };

    app.init();
});
