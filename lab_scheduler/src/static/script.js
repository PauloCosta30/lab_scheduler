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

    // --- Variáveis Globais ---
    const API_BASE_URL = "/api";
    let allRooms = [];
    let selectedSlots = [];
    let currentWeekStartDate; // Apenas a segunda-feira da semana sendo visualizada
    let bookingWindowStatus = null;

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

    // --- LÓGICA DE DATAS (REESCRITA E SIMPLIFICADA) ---
    function getMonday(d) {
        const date = new Date(d);
        const day = date.getUTCDay(); // 0=Dom, 1=Seg, ..., 6=Sab
        const diff = date.getUTCDate() - day + (day === 0 ? -6 : 1); // ajusta para segunda-feira
        return new Date(date.setUTCDate(diff));
    }

    function toYYYYMMDD(date) {
        // Garante que a data esteja em UTC para evitar problemas de fuso horário
        const year = date.getUTCFullYear();
        const month = String(date.getUTCMonth() + 1).padStart(2, '0');
        const day = String(date.getUTCDate()).padStart(2, '0');
        return `${year}-${month}-${day}`;
    }

    // --- Lógica de Carregamento ---
    async function initializeApp() {
        console.log("1. Iniciando App...");
        try {
            // Passo 1: Buscar o status da janela de agendamento
            const response = await fetch(`${API_BASE_URL}/booking-window-status`);
            if (!response.ok) throw new Error(`Falha ao buscar status: ${response.status}`);
            bookingWindowStatus = await response.json();
            console.log("2. Status da janela carregado:", bookingWindowStatus);
            showBookingStatus(bookingWindowStatus.general_message, 'info');

            // Passo 2: Determinar qual semana exibir
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

            // Passo 3: Carregar a escala para a semana determinada
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
            // Define a data global para navegação
            currentWeekStartDate = new Date(`${startDateStr}T12:00:00Z`); // Usar meio-dia UTC para evitar erros de fuso
            if(weekSelector) weekSelector.value = startDateStr;

            // Calcula a data final da semana
            const endDate = new Date(currentWeekStartDate);
            endDate.setUTCDate(currentWeekStartDate.getUTCDate() + 4);
            const endDateStr = toYYYYMMDD(endDate);

            // Busca as salas (se ainda não tiver)
            if (allRooms.length === 0) {
                const roomsResponse = await fetch(`${API_BASE_URL}/rooms`);
                if (!roomsResponse.ok) throw new Error("Falha ao carregar salas.");
                allRooms = await roomsResponse.json();
                console.log("5. Salas carregadas.");
            }

            // Busca os agendamentos
            const bookingsResponse = await fetch(`${API_BASE_URL}/bookings?start_date=${startDateStr}&end_date=${endDateStr}`);
            if (!bookingsResponse.ok) throw new Error("Falha ao carregar agendamentos.");
            const bookings = await bookingsResponse.json();
            console.log(`6. ${bookings.length} agendamentos carregados.`);

            // Renderiza a tabela
            renderScheduleTable(bookings, allRooms, currentWeekStartDate);
            showMessage(scheduleMessage, "Escala carregada com sucesso.", "success");

        } catch (error) {
            console.error("ERRO AO CARREGAR ESCALA:", error);
            showMessage(scheduleMessage, `Erro ao carregar escala: ${error.message}`, "error");
            if(scheduleTableContainer) scheduleTableContainer.innerHTML = ""; // Limpa a tabela em caso de erro
        }
    }

    function renderScheduleTable(bookings, rooms, weekStartDate) {
        console.log("7. Renderizando tabela...");
        if (!scheduleTableContainer || !rooms || rooms.length === 0 || !weekStartDate) {
            console.error("Dados insuficientes para renderizar a tabela.");
            showMessage(scheduleMessage, "Erro interno: não foi possível renderizar a tabela.", "error");
            return;
        }
        
        scheduleTableContainer.innerHTML = ""; // Limpa conteúdo anterior
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
            periods.forEach(p => {
                const th = document.createElement("th");
                th.textContent = p;
                subHeaderRow.appendChild(th);
            });
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
                    
                    const booking = bookings.find(b => b.room_id === room.id && b.booking_date === dateStr && b.period === period);
                    
                    if (booking) {
                        cell.textContent = booking.user_name;
                        cell.classList.add("booked");
                        cell.title = `Reservado por: ${booking.user_name}`;
                    } else {
                        if (checkIfBookingAllowed(dateStr)) {
                            cell.textContent = "Disponível";
                            cell.classList.add("available");
                            cell.dataset.roomId = room.id;
                            cell.dataset.roomName = room.name;
                            cell.dataset.date = dateStr;
                            cell.dataset.period = period;
                            cell.addEventListener("click", handleSlotClick);
                            cell.style.cursor = "pointer";
                            cell.title = "Clique para selecionar";
                        } else {
                            cell.textContent = "Fechado";
                            cell.classList.add("closed");
                            cell.title = "Período de agendamento fechado";
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
    
    function handleSlotClick(event) { /* ... (código desta função permanece o mesmo) ... */ }
    function updateButtonStates() { /* ... (código desta função permanece o mesmo) ... */ }
    async function generatePdf() { /* ... (código desta função permanece o mesmo) ... */ }
    async function createBooking(formData) { /* ... (código desta função permanece o mesmo) ... */ }
    function updateSelectedSlotsSummary() { /* ... (código desta função permanece o mesmo) ... */ }

    // --- Event Listeners ---
    if (loadScheduleButton) {
        loadScheduleButton.addEventListener("click", () => {
            if (weekSelector.value) {
                // A data do seletor pode ser qualquer dia, ajustamos para a segunda-feira daquela semana
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
    
    // ... (outros event listeners do modal, etc.)

    // --- Inicialização ---
    initializeApp();
});
