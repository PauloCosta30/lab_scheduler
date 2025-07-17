document.addEventListener("DOMContentLoaded", () => {
    // --- Elementos DOM ---
    const scheduleTableContainer = document.getElementById("scheduleTableContainer");
    const scheduleMessage = document.getElementById("scheduleMessage");
    const proceedToBookingButton = document.getElementById("proceedToBookingButton");
    const generatePdfButton = document.getElementById("generatePdfButton");
    const weekSelector = document.getElementById("weekSelector");
    const loadScheduleButton = document.getElementById("loadScheduleButton");
    const prevWeekButton = document.getElementById("prevWeekButton");
    const nextWeekButton = document.getElementById("nextWeekButton");
    const bookingStatusMessage = document.getElementById("bookingStatusMessage");
    const bookingModal = document.getElementById("bookingModal");
    const closeModalButton = document.querySelector(".close-button");
    const modalBookingForm = document.getElementById("modalBookingForm");
    const selectedSlotsSummaryList = document.querySelector("#selectedSlotsSummary ul");
    const modalFormMessage = document.getElementById("modalFormMessage");
    const adminLoginLink = document.getElementById("adminLoginLink");

    // --- Variáveis Globais ---
    const API_BASE_URL = "/api";
    let allRooms = [];
    let selectedSlots = [];
    let currentWeekStartDate;
    let bookingWindowStatus = null;
    let isAdminMode = false;
    let adminKey = null;

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
    
    function showBookingStatus(message, type = 'info') {
        if(bookingStatusMessage) {
            bookingStatusMessage.textContent = message;
            bookingStatusMessage.className = `status-message ${type}`;
        }
    }

    function getMonday(d) {
        const date = new Date(d);
        const day = date.getUTCDay();
        const diff = date.getUTCDate() - day + (day === 0 ? -6 : 1);
        return new Date(date.setUTCDate(diff));
    }

    function toYYYYMMDD(date) {
        const year = date.getUTCFullYear();
        const month = String(date.getUTCMonth() + 1).padStart(2, '0');
        const day = String(date.getUTCDate()).padStart(2, '0');
        return `${year}-${month}-${day}`;
    }

    // --- Lógica de Admin ---
    function enterAdminMode() {
        if (isAdminMode) {
            alert("O modo administrador já está ativo.");
            return;
        }
        const key = prompt("Por favor, insira a Chave de Administrador:");
        if (key) {
            adminKey = key;
            isAdminMode = true;
            document.body.insertAdjacentHTML('afterbegin', '<div class="admin-mode-indicator" id="adminModeIndicator">MODO ADMINISTRADOR ATIVADO</div>');
            console.log("Modo Administrador ATIVADO. Recarregando a escala com privilégios de edição.");
            if (currentWeekStartDate) {
                loadScheduleFor(toYYYYMMDD(currentWeekStartDate));
            }
        }
    }

    async function handleAdminCellClick(cell) {
        const roomName = cell.dataset.roomName;
        const date = cell.dataset.date;
        const period = cell.dataset.period;
        const currentHolder = cell.classList.contains('booked') ? cell.textContent.trim() : "";

        const newUserName = prompt(`Editando: ${roomName} - ${date} - ${period}\n\nNome do Usuário Atual: "${currentHolder}"\n\nDigite o novo nome (ou deixe em branco para remover):`, currentHolder);

        if (newUserName === null) {
            console.log("Edição cancelada.");
            return;
        }

        const bookingData = {
            room_id: parseInt(cell.dataset.roomId),
            booking_date: date,
            period: period,
            user_name: newUserName.trim()
        };

        showMessage(scheduleMessage, "Salvando alteração de admin...", "info");

        try {
            const response = await fetch(`${API_BASE_URL}/admin/booking`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-Admin-Key": adminKey
                },
                body: JSON.stringify(bookingData)
            });

            const result = await response.json();
            if (!response.ok) throw new Error(result.error || `Erro ${response.status}`);

            showMessage(scheduleMessage, result.message, "success");
            
            // --- CORREÇÃO APLICADA AQUI ---
            // Verifica se a string newUserName, depois de remover espaços, tem algum conteúdo.
            if (newUserName.trim()) {
                cell.textContent = newUserName.trim();
                cell.className = 'schedule-cell booked admin-editable';
            } else {
                cell.textContent = "Disponível";
                cell.className = 'schedule-cell available admin-editable';
            }

        } catch (error) {
            console.error("Erro na edição de admin:", error);
            showMessage(scheduleMessage, `Falha na edição: ${error.message}`, "error");
        }
    }

    // --- Lógica de Carregamento ---
    async function initializeApp() {
        console.log("1. Iniciando App...");
        try {
            const response = await fetch(`${API_BASE_URL}/booking-window-status`);
            if (!response.ok) throw new Error(`Falha ao buscar status: ${response.status}`);
            bookingWindowStatus = await response.json();
            console.log("2. Status da janela carregado:", bookingWindowStatus);
            showBookingStatus(bookingWindowStatus.general_message, 'info');

            const now = new Date();
            let referenceDate = now;
            const currentDay = now.getDay();
            const currentHour = now.getHours();

            if ((currentDay === 4 && currentHour >= 18) || currentDay >= 5 || currentDay === 0) {
                console.log("3. Decisão: Mostrar próxima semana.");
                const nextWeek = new Date(now);
                nextWeek.setDate(now.getDate() + 7);
                referenceDate = nextWeek;
            } else {
                console.log("3. Decisão: Mostrar semana atual.");
            }

            const mondayOfTargetWeek = getMonday(referenceDate);
            await loadScheduleFor(toYYYYMMDD(mondayOfTargetWeek));

        } catch (error) {
            console.error("ERRO CRÍTICO NA INICIALIZAÇÃO:", error);
            showMessage(scheduleMessage, `Erro ao inicializar: ${error.message}`, "error");
            showBookingStatus("Erro de conexão com o servidor.", "error");
        }
    }

    async function loadScheduleFor(startDateStr) {
        console.log(`4. Carregando escala para a semana de ${startDateStr}`);
        showMessage(scheduleMessage, "Carregando escala...", "");

        try {
            currentWeekStartDate = new Date(`${startDateStr}T12:00:00Z`);
            if(weekSelector) weekSelector.value = startDateStr;

            const endDate = new Date(currentWeekStartDate);
            endDate.setUTCDate(currentWeekStartDate.getUTCDate() + 4);
            const endDateStr = toYYYYMMDD(endDate);

            if (allRooms.length === 0) {
                const roomsResponse = await fetch(`${API_BASE_URL}/rooms`);
                if (!roomsResponse.ok) throw new Error("Falha ao carregar salas.");
                allRooms = await roomsResponse.json();
                console.log("5. Salas carregadas.");
            }

            const bookingsResponse = await fetch(`${API_BASE_URL}/bookings?start_date=${startDateStr}&end_date=${endDateStr}`);
            if (!bookingsResponse.ok) throw new Error("Falha ao carregar agendamentos.");
            const bookings = await bookingsResponse.json();
            console.log(`6. ${bookings.length} agendamentos carregados.`);

            renderScheduleTable(bookings, allRooms, currentWeekStartDate);
            showMessage(scheduleMessage, "Escala carregada com sucesso.", "success");

        } catch (error) {
            console.error("ERRO AO CARREGAR ESCALA:", error);
            showMessage(scheduleMessage, `Erro ao carregar escala: ${error.message}`, "error");
            if(scheduleTableContainer) scheduleTableContainer.innerHTML = "";
        }
    }

    function renderScheduleTable(bookings, rooms, weekStartDate) {
        console.log("7. Renderizando tabela...");
        if (!scheduleTableContainer || !rooms || rooms.length === 0 || !weekStartDate) {
            console.error("Dados insuficientes para renderizar a tabela.");
            return;
        }
        
        scheduleTableContainer.innerHTML = "";
        selectedSlots = [];
        updateButtonStates();

        const table = document.createElement("table");
        table.className = "schedule-table";
        const thead = document.createElement("thead");
        const tbody = document.createElement("tbody");

        const headerRow = document.createElement("tr");
        headerRow.innerHTML = "<th>Sala</th>";
        const days = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta"];
        const periods = ["Manhã", "Tarde"];
        const datesOfWeek = [];

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
        for (let i = 0; i < 5; i++) {
            periods.forEach(() => subHeaderRow.innerHTML += "<th>Manhã</th><th>Tarde</th>");
        }
        thead.appendChild(subHeaderRow);
        table.appendChild(thead);

        rooms.forEach(room => {
            const row = document.createElement("tr");
            const roomCell = document.createElement("td");
            roomCell.textContent = room.name;
            roomCell.className = "room-name";
            row.appendChild(roomCell);

            datesOfWeek.forEach(dateStr => {
                periods.forEach(period => {
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
                        if (booking) {
                            cell.textContent = booking.user_name;
                            cell.classList.add("booked");
                        } else {
                            cell.textContent = "Disponível";
                            cell.classList.add("available");
                        }
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
        console.log("8. Tabela renderizada com sucesso.");
    }
    
    function checkIfBookingAllowed(dateStr) {
        if (!bookingWindowStatus) return false;
        const slotDate = new Date(`${dateStr}T12:00:00Z`);
        const today = getMonday(new Date());
        const nextWeek = new Date(today);
        nextWeek.setUTCDate(today.getUTCDate() + 7);

        if (slotDate >= today && slotDate < nextWeek) {
            return bookingWindowStatus.current_week.open;
        } else if (slotDate >= nextWeek && slotDate < new Date(nextWeek.getTime() + 7 * 24 * 60 * 60 * 1000)) {
            return bookingWindowStatus.next_week.open;
        }
        return false;
    }
    
    function handleSlotClick(event) {
        const cell = event.currentTarget;
        if (cell.classList.contains("booked") || cell.classList.contains("closed")) return;

        const slotData = {
            roomId: parseInt(cell.dataset.roomId),
            roomName: cell.dataset.roomName,
            date: cell.dataset.date,
            period: cell.dataset.period,
            cellRef: cell
        };

        const existingIndex = selectedSlots.findIndex(s => 
            s.roomId === slotData.roomId && s.date === slotData.date && s.period === slotData.period
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
        updateButtonStates();
    }

    function updateButtonStates() {
        if (proceedToBookingButton) proceedToBookingButton.disabled = false;
        if (generatePdfButton) generatePdfButton.disabled = !currentWeekStartDate;
    }

    async function generatePdf() {
        if (!currentWeekStartDate) {
            showMessage(scheduleMessage, "Carregue uma escala primeiro.", "error");
            return;
        }
        const startDate = toYYYYMMDD(currentWeekStartDate);
        const endDate = new Date(currentWeekStartDate);
        endDate.setUTCDate(currentWeekStartDate.getUTCDate() + 4);
        const endDateStr = toYYYYMMDD(endDate);

        generatePdfButton.disabled = true;
        generatePdfButton.textContent = "Gerando...";
        showMessage(scheduleMessage, "Gerando PDF...", "info");
        
        try {
            const response = await fetch(`${API_BASE_URL}/generate-pdf?start_date=${startDate}&end_date=${endDateStr}`);
            if (!response.ok) throw new Error(`Erro do servidor: ${response.statusText}`);
            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.style.display = "none";
            a.href = url;
            a.download = `escala_agendamentos_${startDate}_a_${endDateStr}.pdf`;
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
            document.body.removeChild(a);
            showMessage(scheduleMessage, "PDF gerado com sucesso!", "success");
        } catch (error) {
            console.error("Falha ao gerar PDF:", error);
            showMessage(scheduleMessage, `Erro ao gerar PDF: ${error.message}`, "error");
        } finally {
            generatePdfButton.disabled = false;
            generatePdfButton.textContent = "Gerar PDF da Escala";
        }
    }

    async function createBooking(formData) {
        const userName = formData.get("userName");
        const userEmail = formData.get("userEmail");
        if (!userName || !userEmail) {
            showMessage(modalFormMessage, "Nome e E-mail são obrigatórios.", "error");
            return;
        }
        if (selectedSlots.length === 0 && !formData.get("observation").trim()) {
            showMessage(modalFormMessage, "É necessário uma observação para agendamentos sem sala.", "error");
            return;
        }

        const bookingData = {
            user_name: userName,
            user_email: userEmail,
            coordinator_name: formData.get("coordinatorName"),
            observation: formData.get("observation"),
            slots: selectedSlots.map(s => ({ room_id: s.roomId, booking_date: s.date, period: s.period }))
        };

        showMessage(modalFormMessage, "Enviando agendamento...", "info");

        try {
            const response = await fetch(`${API_BASE_URL}/bookings`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(bookingData)
            });
            const result = await response.json();
            if (!response.ok) throw new Error(result.error || `Erro ${response.status}`);
            
            showMessage(modalFormMessage, result.message, "success");
            setTimeout(() => {
                bookingModal.style.display = "none";
                loadScheduleFor(toYYYYMMDD(currentWeekStartDate)); // Recarrega a escala
            }, 2000);

        } catch (error) {
            showMessage(modalFormMessage, `Falha no agendamento: ${error.message}`, "error");
        }
    }

    function updateSelectedSlotsSummary() {
        if (!selectedSlotsSummaryList) return;
        selectedSlotsSummaryList.innerHTML = "";
        if (selectedSlots.length === 0) {
            selectedSlotsSummaryList.innerHTML = "<li><em>Nenhum horário selecionado - Agendamento somente observação</em></li>";
            return;
        }
        selectedSlots.forEach(slot => {
            const li = document.createElement("li");
            li.textContent = `${slot.roomName} - ${slot.date} - ${slot.period}`;
            selectedSlotsSummaryList.appendChild(li);
        });
    }

    // --- Event Listeners ---
    if (adminLoginLink) {
        adminLoginLink.addEventListener("click", (e) => {
            e.preventDefault();
            enterAdminMode();
        });
    }

    if (loadScheduleButton) {
        loadScheduleButton.addEventListener("click", () => {
            if (weekSelector.value) {
                const selectedDate = new Date(`${weekSelector.value}T12:00:00Z`);
                const selectedMonday = getMonday(selectedDate);
                loadScheduleFor(toYYYYMMDD(selectedMonday));
            }
        });
    }

    if (prevWeekButton) {
        prevWeekButton.addEventListener("click", () => {
            if (currentWeekStartDate) {
                const prevMonday = new Date(currentWeekStartDate);
                prevMonday.setUTCDate(prevMonday.getUTCDate() - 7);
                loadScheduleFor(toYYYYMMDD(prevMonday));
            }
        });
    }

    if (nextWeekButton) {
        nextWeekButton.addEventListener("click", () => {
            if (currentWeekStartDate) {
                const nextMonday = new Date(currentWeekStartDate);
                nextMonday.setUTCDate(nextMonday.getUTCDate() + 7);
                loadScheduleFor(toYYYYMMDD(nextMonday));
            }
        });
    }
    
    if (generatePdfButton) { generatePdfButton.addEventListener("click", generatePdf); }
    if (closeModalButton) { closeModalButton.addEventListener("click", () => bookingModal.style.display = "none"); }
    window.addEventListener("click", (event) => { if (event.target === bookingModal) bookingModal.style.display = "none"; });
    if (modalBookingForm) { modalBookingForm.addEventListener("submit", (e) => { e.preventDefault(); createBooking(new FormData(modalBookingForm)); }); }
    if (proceedToBookingButton) { proceedToBookingButton.addEventListener("click", () => { updateSelectedSlotsSummary(); bookingModal.style.display = "block"; }); }

    // --- Inicialização ---
    initializeApp();
});
