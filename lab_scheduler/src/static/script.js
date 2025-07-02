document.addEventListener("DOMContentLoaded", () => {
    // DOM Elements for Modal and New Flow
    const scheduleTableContainer = document.getElementById("scheduleTableContainer");
    const scheduleMessage = document.getElementById("scheduleMessage");
    const proceedToBookingButton = document.getElementById("proceedToBookingButton");
    const generatePdfButton = document.getElementById("generatePdfButton");
    const weekSelector = document.getElementById("weekSelector");
    const loadScheduleButton = document.getElementById("loadScheduleButton");

    // DOM Elements for Booking Status
    const bookingStatusMessage = document.getElementById("bookingStatusMessage");
    const currentWeekStatus = document.getElementById("currentWeekStatus");
    const nextWeekStatus = document.getElementById("nextWeekStatus");

    const bookingModal = document.getElementById("bookingModal");
    const closeModalButton = document.querySelector(".close-button");
    const modalBookingForm = document.getElementById("modalBookingForm");
    const selectedSlotsSummaryList = document.querySelector("#selectedSlotsSummary ul");
    const modalFormMessage = document.getElementById("modalFormMessage");

    const API_BASE_URL = "/api";
    let allRooms = [];
    let selectedSlots = [];
    let currentFetchedBookings = [];
    let currentWeekStartDate;
    let bookingWindowStatus = null;

    // --- Helper Functions for Date Handling (UTC) ---
    function getTodayUTC() {
        const today = new Date();
        return new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate()));
    }

    function parseDateStrToUTC(dateStr) {
        const [year, month, day] = dateStr.split("-").map(Number);
        return new Date(Date.UTC(year, month - 1, day));
    }

    // Nova função para verificar se ainda está dentro do prazo de agendamento (até quarta 23:59)
    function isWithinBookingDeadline(slotDateStr) {
        try {
            const slotDate = parseDateStrToUTC(slotDateStr);
            const now = new Date(); // Data/hora atual local
            
            // Calcular a segunda-feira da semana do slot
            const slotDayOfWeek = slotDate.getUTCDay();
            const diffToMonday = slotDayOfWeek === 0 ? -6 : 1 - slotDayOfWeek;
            const slotWeekMonday = new Date(slotDate.valueOf());
            slotWeekMonday.setUTCDate(slotDate.getUTCDate() + diffToMonday);
            
            // Calcular a quarta-feira da mesma semana às 23:59:59
            const slotWeekWednesday = new Date(slotWeekMonday.valueOf());
            slotWeekWednesday.setUTCDate(slotWeekMonday.getUTCDate() + 2); // +2 dias = quarta
            slotWeekWednesday.setUTCHours(23, 59, 59, 999); // 23:59:59.999
            
            // Converter para horário local do usuário para comparação
            const deadlineLocal = new Date(slotWeekWednesday.getTime());
            
            console.log(`Verificando prazo para ${slotDateStr}:`);
            console.log(`  Slot date: ${slotDate.toISOString()}`);
            console.log(`  Deadline (quarta 23:59): ${deadlineLocal.toISOString()}`);
            console.log(`  Now: ${now.toISOString()}`);
            console.log(`  Dentro do prazo: ${now <= deadlineLocal}`);
            
            return now <= deadlineLocal;
            
        } catch (error) {
            console.error("Erro ao verificar prazo de agendamento:", error);
            return false;
        }
    }

    // --- Helper Functions for Messages ---
    function showModalMessage(message, type) {
        if (modalFormMessage) {
            modalFormMessage.textContent = message;
            modalFormMessage.className = `message ${type}`;
            if (type === "success") {
                setTimeout(() => {
                    modalFormMessage.textContent = "";
                    modalFormMessage.className = "message";
                }, 4000);
            }
        }
    }

    function showScheduleMessage(message, type) {
        if (scheduleMessage) {
            scheduleMessage.textContent = message;
            scheduleMessage.className = `message ${type}`;
            if (type !== "error" && type !== "info") {
                setTimeout(() => {
                    scheduleMessage.textContent = "";
                    scheduleMessage.className = "message";
                }, 3000);
            }
        }
    }

    function showBookingStatusMessage(message, type) {
        if (bookingStatusMessage) {
            bookingStatusMessage.textContent = message;
            bookingStatusMessage.className = `status-message ${type}`;
        }
    }

    // --- Booking Window Status Functions ---
    async function fetchBookingWindowStatus() {
        try {
            const response = await fetch(`${API_BASE_URL}/booking-window-status`);
            if (!response.ok) {
                throw new Error(`Erro ao buscar status: ${response.statusText}`);
            }
            bookingWindowStatus = await response.json();
            updateBookingStatusDisplay();
            console.log("Status da janela de agendamento carregado:", bookingWindowStatus);
            return true;
        } catch (error) {
            console.error("Falha ao buscar status da janela de agendamento:", error);
            showBookingStatusMessage("Não foi possível verificar o status do agendamento", "error");
            return false;
        }
    }

    function updateBookingStatusDisplay() {
        if (!bookingWindowStatus) return;

        showBookingStatusMessage("As escolhas para a semana atual sempre serão encerradas às quartas-feiras, às 23:59, e a escala da próxima semana será liberada todas as sextas-feiras, às 18h.", "info");

        // Ocultar os status individuais da semana atual e próxima semana, pois a mensagem é fixa
        if (currentWeekStatus) currentWeekStatus.style.display = "none";
        if (nextWeekStatus) nextWeekStatus.style.display = "none";
    }

    // --- Room Data --- 
    async function fetchAllRooms() {
        try {
            console.log("Buscando salas...");
            const response = await fetch(`${API_BASE_URL}/rooms`);
            if (!response.ok) {
                throw new Error(`Erro ao buscar salas: ${response.statusText}`);
            }
            allRooms = await response.json();
            console.log(`Carregadas ${allRooms.length} salas:`, allRooms);
            return true;
        } catch (error) {
            console.error("Falha ao buscar salas:", error);
            showScheduleMessage("Não foi possível carregar dados das salas. Tente recarregar.", "error");
            return false;
        }
    }

    // --- Schedule Logic (Loading and Rendering) ---
    async function loadScheduleData(inputDate = null) {
        console.log("Iniciando carregamento da escala...");
        
        let startDate, endDate;
        const todayUTC = getTodayUTC();

        try {
            let referenceDate;
            if (inputDate) {
                console.log("Data de entrada:", inputDate);
                referenceDate = parseDateStrToUTC(inputDate);
            } else {
                referenceDate = todayUTC;
            }

            // Calcular segunda-feira da semana
            const dayOfWeek = referenceDate.getUTCDay();
            const diffToMonday = dayOfWeek === 0 ? -6 : 1 - dayOfWeek;
            startDate = new Date(referenceDate.valueOf());
            startDate.setUTCDate(referenceDate.getUTCDate() + diffToMonday);
            
            endDate = new Date(startDate.valueOf());
            endDate.setUTCDate(startDate.getUTCDate() + 4);
            
            currentWeekStartDate = startDate; 

            const startDateStrAPI = startDate.toISOString().split("T")[0];
            const endDateStrAPI = endDate.toISOString().split("T")[0];
            
            showScheduleMessage("Carregando escala...", "");
            
            console.log(`Carregando agendamentos de ${startDateStrAPI} até ${endDateStrAPI}`);
            
            // Primeiro, verificar se temos as salas carregadas
            if (allRooms.length === 0) {
                console.log("Salas não carregadas, carregando...");
                const roomsLoaded = await fetchAllRooms();
                if (!roomsLoaded) {
                    throw new Error("Não foi possível carregar as salas");
                }
            }
            
            // Carregar agendamentos
            const response = await fetch(`${API_BASE_URL}/bookings?start_date=${startDateStrAPI}&end_date=${endDateStrAPI}`);
            if (!response.ok) {
                throw new Error(`Erro ao buscar agendamentos: ${response.statusText}`);
            }
            currentFetchedBookings = await response.json();
            console.log(`Carregados ${currentFetchedBookings.length} agendamentos:`, currentFetchedBookings);
            
            renderScheduleTable(currentFetchedBookings, allRooms, currentWeekStartDate);
            showScheduleMessage("Escala carregada.", "success");
            
        } catch (error) {
            console.error("Falha ao carregar escala:", error);
            showScheduleMessage(`Não foi possível carregar a escala: ${error.message}`, "error");
            if (scheduleTableContainer) {
                scheduleTableContainer.innerHTML = "<p>Erro ao carregar escala.</p>";
            }
        }
    }

    function renderScheduleTable(bookings, roomsData, weekStartDateObj) {
        console.log("Renderizando tabela da escala...");
        console.log("Agendamentos recebidos:", bookings);
        
        if (!scheduleTableContainer) {
            console.error("scheduleTableContainer não encontrado");
            return;
        }

        // Verificar se temos dados válidos
        if (!roomsData || roomsData.length === 0) {
            console.error("Dados de salas não encontrados ou vazios");
            scheduleTableContainer.innerHTML = "<p>Erro: Dados de salas não disponíveis.</p>";
            return;
        }

        if (!weekStartDateObj) {
            console.error("Data de início da semana não definida");
            scheduleTableContainer.innerHTML = "<p>Erro: Data da semana não definida.</p>";
            return;
        }

        scheduleTableContainer.innerHTML = "";
        selectedSlots = [];
        updateButtonStates();

        // Adicionar aviso sobre agendamentos somente observação
        const infoDiv = document.createElement("div");
        infoDiv.className = "booking-info";
        infoDiv.style.cssText = "background: #e8f4fd; border: 1px solid #bee5eb; padding: 10px; margin-bottom: 15px; border-radius: 4px; color: #0c5460;";
        infoDiv.innerHTML = `
            <strong>💡 Dica:</strong> Se todas as salas estiverem ocupadas, você pode fazer um agendamento apenas com observação para solicitar encaixe. 
            Clique em "Prosseguir com o agendamento" mesmo sem selecionar nenhuma sala.
        `;
        scheduleTableContainer.appendChild(infoDiv);

        const table = document.createElement("table");
        table.className = "schedule-table";
        const thead = document.createElement("thead");
        const tbody = document.createElement("tbody");

        // Cabeçalho principal
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

        // Subcabeçalho (Manhã/Tarde)
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

        // Corpo da tabela
        roomsData.forEach(room => {
            const row = document.createElement("tr");
            const roomCell = document.createElement("td");
            roomCell.textContent = room.name;
            roomCell.className = "room-name";
            row.appendChild(roomCell);

            datesOfWeek.forEach(dateStr => {
                periods.forEach(period => {
                    const cell = document.createElement("td");
                    cell.className = "schedule-cell";
                    
                    // Buscar agendamento para esta sala, data e período
                    const booking = bookings.find(b => 
                        b.room_id === room.id && 
                        b.booking_date === dateStr && 
                        b.period === period
                    );
                    
                    console.log(`Verificando agendamento para Sala ${room.id} (${room.name}), Data ${dateStr}, Período ${period}:`, booking);
                    
                    if (booking) {
                        // Sala já está reservada
                        cell.textContent = booking.user_name;
                        cell.classList.add("booked");
                        cell.title = `Reservado por: ${booking.user_name}`;
                        console.log(`Célula marcada como ocupada: ${room.name} - ${dateStr} - ${period} por ${booking.user_name}`);
                    } else {
                        // Verificar se o agendamento está permitido para esta data
                        const isBookingAllowed = checkIfBookingAllowed(dateStr);
                        
                        if (isBookingAllowed) {
                            // Disponível para agendamento
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
                            // Período de agendamento fechado
                            cell.textContent = "Fechado";
                            cell.classList.add("closed");
                            cell.title = "Período de agendamento fechado";
                        }
                    }
                });
            });
            tbody.appendChild(row);
        });
        table.appendChild(tbody);
        scheduleTableContainer.appendChild(table);
    }

    function checkIfBookingAllowed(dateStr) {
        const today = getTodayUTC();
        const slotDate = parseDateStrToUTC(dateStr);

        // Agendamentos só podem ser feitos para datas futuras ou o dia atual
        if (slotDate < today) {
            return false;
        }

        // Verificar se está dentro do prazo de agendamento (até quarta 23:59 da semana do agendamento)
        return isWithinBookingDeadline(dateStr);
    }

    // --- Slot Selection and Modal Logic ---
    function handleSlotClick(event) {
        const cell = event.target;
        if (cell.classList.contains("available")) {
            const roomId = cell.dataset.roomId;
            const roomName = cell.dataset.roomName;
            const date = cell.dataset.date;
            const period = cell.dataset.period;

            const existingIndex = selectedSlots.findIndex(slot => 
                slot.roomId === roomId && 
                slot.date === date && 
                slot.period === period
            );

            if (existingIndex > -1) {
                // Remover seleção
                selectedSlots.splice(existingIndex, 1);
                cell.classList.remove("selected");
            } else {
                // Adicionar seleção
                selectedSlots.push({ roomId, roomName, date, period });
                cell.classList.add("selected");
            }
            updateButtonStates();
            updateSelectedSlotsSummary();
        }
    }

    function updateSelectedSlotsSummary() {
        if (!selectedSlotsSummaryList) return;
        
        selectedSlotsSummaryList.innerHTML = "";
        if (selectedSlots.length === 0) {
            selectedSlotsSummaryList.innerHTML = "<li>Nenhum horário selecionado. Você pode prosseguir para fazer um agendamento de observação.</li>";
        } else {
            selectedSlots.forEach(slot => {
                const li = document.createElement("li");
                li.textContent = `${slot.roomName} - ${new Date(slot.date + 'T00:00:00Z').toLocaleDateString('pt-BR', { timeZone: 'UTC' })} - ${slot.period}`;
                selectedSlotsSummaryList.appendChild(li);
            });
        }
    }

    function updateButtonStates() {
        if (proceedToBookingButton) {
            proceedToBookingButton.disabled = false; // Sempre habilitado para permitir agendamento de observação
        }
        if (generatePdfButton) {
            generatePdfButton.disabled = currentFetchedBookings.length === 0;
        }
    }

    // Event Listeners
    if (proceedToBookingButton) {
        proceedToBookingButton.addEventListener("click", () => {
            if (bookingModal) {
                bookingModal.style.display = "block";
                updateSelectedSlotsSummary();
                if (modalFormMessage) {
                    modalFormMessage.textContent = "";
                    modalFormMessage.className = "message";
                }
            }
        });
    }

    if (closeModalButton) {
        closeModalButton.addEventListener("click", () => {
            if (bookingModal) {
                bookingModal.style.display = "none";
            }
        });
    }

    window.addEventListener("click", (event) => {
        if (event.target === bookingModal) {
            if (bookingModal) {
                bookingModal.style.display = "none";
            }
        }
    });

    if (modalBookingForm) {
        modalBookingForm.addEventListener("submit", async (event) => {
            event.preventDefault();

            const userName = document.getElementById("userName")?.value;
            const userEmail = document.getElementById("userEmail")?.value;
            const userPhone = document.getElementById("userPhone")?.value;
            const observation = document.getElementById("observation")?.value;

            if (!userName || !userEmail || !userPhone) {
                showModalMessage("Por favor, preencha nome, e-mail e telefone.", "error");
                return;
            }

            const bookingData = {
                user_name: userName,
                user_email: userEmail,
                user_phone: userPhone,
                observation: observation || "",
                slots: selectedSlots.map(slot => ({
                    room_id: slot.roomId,
                    booking_date: slot.date,
                    period: slot.period
                })),
            };

            console.log("Enviando dados de agendamento:", bookingData);

            try {
                const response = await fetch(`${API_BASE_URL}/bookings`, {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                    },
                    body: JSON.stringify(bookingData),
                });

                const result = await response.json();

                if (response.ok) {
                    showModalMessage(result.message || "Agendamento realizado com sucesso!", "success");
                    modalBookingForm.reset();
                    selectedSlots = [];
                    updateSelectedSlotsSummary();
                    // Recarregar a escala para refletir o novo agendamento
                    if (currentWeekStartDate) {
                        loadScheduleData(currentWeekStartDate.toISOString().split("T")[0]);
                    }
                } else {
                    showModalMessage(result.message || "Erro ao agendar. Tente novamente.", "error");
                }
            } catch (error) {
                console.error("Erro na requisição de agendamento:", error);
                showModalMessage("Erro de conexão. Tente novamente.", "error");
            }
        });
    }

    // --- PDF Generation ---
    if (generatePdfButton) {
        generatePdfButton.addEventListener("click", async () => {
            if (currentFetchedBookings.length === 0) {
                showScheduleMessage("Nenhum agendamento para gerar PDF.", "info");
                return;
            }

            showScheduleMessage("Gerando PDF...", "");
            try {
                const startDateStr = currentWeekStartDate.toISOString().split("T")[0];
                const endDate = new Date(currentWeekStartDate.valueOf());
                endDate.setUTCDate(currentWeekStartDate.getUTCDate() + 4);
                const endDateStr = endDate.toISOString().split("T")[0];

                const response = await fetch(`${API_BASE_URL}/generate-pdf?start_date=${startDateStr}&end_date=${endDateStr}`);
                if (!response.ok) {
                    throw new Error(`Erro ao gerar PDF: ${response.statusText}`);
                }
                const blob = await response.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement("a");
                a.href = url;
                a.download = `escala_${startDateStr}_${endDateStr}.pdf`;
                document.body.appendChild(a);
                a.click();
                a.remove();
                window.URL.revokeObjectURL(url);
                showScheduleMessage("PDF gerado com sucesso!", "success");
            } catch (error) {
                console.error("Falha ao gerar PDF:", error);
                showScheduleMessage(`Não foi possível gerar o PDF: ${error.message}`, "error");
            }
        });
    }

    // --- Week Selector Logic ---
    function populateWeekSelector() {
        if (!weekSelector) return;
        
        const today = getTodayUTC();
        const options = [];

        // Adicionar a semana atual
        let currentWeekMonday = new Date(today.valueOf());
        const dayOfWeek = currentWeekMonday.getUTCDay();
        const diffToMonday = dayOfWeek === 0 ? -6 : 1 - dayOfWeek;
        currentWeekMonday.setUTCDate(currentWeekMonday.getUTCDate() + diffToMonday);
        options.push({ date: currentWeekMonday, text: "Semana Atual" });

        // Adicionar as próximas 3 semanas
        for (let i = 1; i <= 3; i++) {
            const nextWeekMonday = new Date(currentWeekMonday.valueOf());
            nextWeekMonday.setUTCDate(currentWeekMonday.getUTCDate() + (i * 7));
            options.push({
                date: nextWeekMonday,
                text: `Próxima Semana ${i} (${nextWeekMonday.toLocaleDateString("pt-BR", {day:"2-digit", month:"2-digit", timeZone: "UTC"})})`
            });
        }

        weekSelector.innerHTML = "";
        options.forEach((opt, index) => {
            const optionElement = document.createElement("option");
            optionElement.value = opt.date.toISOString().split("T")[0];
            optionElement.textContent = opt.text;
            if (index === 0) {
                optionElement.selected = true; // Selecionar a semana atual por padrão
            }
            weekSelector.appendChild(optionElement);
        });
    }

    if (loadScheduleButton) {
        loadScheduleButton.addEventListener("click", () => {
            const selectedDate = weekSelector?.value;
            if (selectedDate) {
                loadScheduleData(selectedDate);
            }
        });
    }

    // --- Initial Load ---
    async function initializePage() {
        populateWeekSelector();
        await fetchBookingWindowStatus();
        await loadScheduleData();
    }

    initializePage();
});
