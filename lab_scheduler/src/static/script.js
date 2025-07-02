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

    // Debug helper function
    function debugLog(message, data = null) {
        console.log(`[DEBUG] ${message}`, data ? data : '');
    }

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
            
            debugLog(`Verificando prazo para ${slotDateStr}:`, {
                slotDate: slotDate.toISOString(),
                deadline: deadlineLocal.toISOString(),
                now: now.toISOString(),
                withinDeadline: now <= deadlineLocal
            });
            
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
        debugLog(`Schedule Message: [${type}] ${message}`);
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
        debugLog(`Booking Status Message: [${type}] ${message}`);
        if (bookingStatusMessage) {
            bookingStatusMessage.textContent = message;
            bookingStatusMessage.className = `status-message ${type}`;
        }
    }

    // --- Booking Window Status Functions ---
    async function fetchBookingWindowStatus() {
        debugLog("Fetching booking window status...");
        try {
            const response = await fetch(`${API_BASE_URL}/booking-window-status`);
            debugLog(`Booking status response: ${response.status} ${response.statusText}`);
            
            if (!response.ok) {
                throw new Error(`Erro ao buscar status: ${response.status} ${response.statusText}`);
            }
            
            bookingWindowStatus = await response.json();
            debugLog("Booking window status loaded:", bookingWindowStatus);
            updateBookingStatusDisplay();
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
        debugLog("Fetching all rooms...");
        try {
            const response = await fetch(`${API_BASE_URL}/rooms`);
            debugLog(`Rooms response: ${response.status} ${response.statusText}`);
            
            if (!response.ok) {
                throw new Error(`Erro ao buscar salas: ${response.status} ${response.statusText}`);
            }
            
            allRooms = await response.json();
            debugLog(`Loaded ${allRooms.length} rooms:`, allRooms);
            
            if (!Array.isArray(allRooms) || allRooms.length === 0) {
                throw new Error("Nenhuma sala encontrada ou formato inválido");
            }
            
            return true;
        } catch (error) {
            console.error("Falha ao buscar salas:", error);
            showScheduleMessage(`Não foi possível carregar dados das salas: ${error.message}`, "error");
            return false;
        }
    }

    // --- Schedule Logic (Loading and Rendering) ---
    async function loadScheduleData(inputDate = null) {
        debugLog("Starting schedule data load...", { inputDate });
        
        let startDate, endDate;
        const todayUTC = getTodayUTC();

        try {
            // Verificar se os elementos DOM existem
            if (!scheduleTableContainer) {
                throw new Error("Element scheduleTableContainer not found");
            }

            let referenceDate;
            if (inputDate) {
                debugLog("Using input date:", inputDate);
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
            
            debugLog(`Loading bookings from ${startDateStrAPI} to ${endDateStrAPI}`);
            showScheduleMessage("Carregando escala...", "");
            
            // Primeiro, verificar se temos as salas carregadas
            if (allRooms.length === 0) {
                debugLog("Rooms not loaded, loading now...");
                const roomsLoaded = await fetchAllRooms();
                if (!roomsLoaded) {
                    throw new Error("Não foi possível carregar as salas");
                }
            }
            
            // Carregar agendamentos
            debugLog("Fetching bookings...");
            const bookingsUrl = `${API_BASE_URL}/bookings?start_date=${startDateStrAPI}&end_date=${endDateStrAPI}`;
            debugLog("Bookings URL:", bookingsUrl);
            
            const response = await fetch(bookingsUrl);
            debugLog(`Bookings response: ${response.status} ${response.statusText}`);
            
            if (!response.ok) {
                const errorText = await response.text();
                debugLog("Bookings error response:", errorText);
                throw new Error(`Erro ao buscar agendamentos: ${response.status} ${response.statusText}`);
            }
            
            currentFetchedBookings = await response.json();
            debugLog(`Loaded ${currentFetchedBookings.length} bookings:`, currentFetchedBookings);
            
            // Verificar se os dados estão no formato esperado
            if (!Array.isArray(currentFetchedBookings)) {
                throw new Error("Formato inválido de agendamentos recebido");
            }
            
            renderScheduleTable(currentFetchedBookings, allRooms, currentWeekStartDate);
            showScheduleMessage("Escala carregada com sucesso.", "success");
            
        } catch (error) {
            console.error("Falha ao carregar escala:", error);
            showScheduleMessage(`Não foi possível carregar a escala: ${error.message}`, "error");
            if (scheduleTableContainer) {
                scheduleTableContainer.innerHTML = `<p>Erro ao carregar escala: ${error.message}</p>`;
            }
        }
    }

    function renderScheduleTable(bookings, roomsData, weekStartDateObj) {
        debugLog("Starting table render...", {
            bookingsCount: bookings.length,
            roomsCount: roomsData.length,
            weekStart: weekStartDateObj?.toISOString()
        });
        
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
                    
                    // Usar 'period' diretamente, sem conversão
                    const booking = bookings.find(b => 
                        b.room_id === room.id && 
                        b.booking_date === dateStr && 
                        b.period === period
                    );
                    
                    debugLog(`Checking booking for Room ${room.id} (${room.name}), Date ${dateStr}, Period ${period}:`, booking);
                    
                    if (booking) {
                        // Sala já está reservada
                        cell.textContent = booking.user_name;
                        cell.classList.add("booked");
                        cell.title = `Reservado por: ${booking.user_name}`;
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
                    row.appendChild(cell);
                });
            });
            tbody.appendChild(row);
        });
        
        table.appendChild(tbody);
        scheduleTableContainer.appendChild(table);
        
        debugLog("Table rendered successfully");
    }

    function checkIfBookingAllowed(dateStr) {
        debugLog(`Checking if booking is allowed for ${dateStr}`);
        
        if (!bookingWindowStatus) {
            debugLog("Booking window status not available");
            return false;
        }

        try {
            const slotDate = parseDateStrToUTC(dateStr);
            const todayUTC = getTodayUTC();
            
            // Calcular segunda-feira da semana atual (UTC)
            const currentWeekMonday = new Date(todayUTC.valueOf());
            const dayOffset = todayUTC.getUTCDay() === 0 ? 6 : todayUTC.getUTCDay() - 1;
            currentWeekMonday.setUTCDate(todayUTC.getUTCDate() - dayOffset);
            
            const nextWeekMonday = new Date(currentWeekMonday.getTime() + 7 * 24 * 60 * 60 * 1000);

            // Verificar se o slot é da semana atual
            if (slotDate >= currentWeekMonday && slotDate < nextWeekMonday) {
                // Para semana atual, verificar se ainda está dentro do prazo (até quarta 23:59)
                const withinDeadline = isWithinBookingDeadline(dateStr);
                const allowed = bookingWindowStatus.current_week.open && withinDeadline;
                debugLog(`Current week - ${dateStr}: window=${bookingWindowStatus.current_week.open}, deadline=${withinDeadline}, allowed=${allowed}`);
                return allowed;
                
            } else if (slotDate >= nextWeekMonday && slotDate < new Date(nextWeekMonday.getTime() + 7 * 24 * 60 * 60 * 1000)) {
                const allowed = bookingWindowStatus.next_week.open;
                debugLog(`Next week - ${dateStr}: ${allowed ? 'ALLOWED' : 'CLOSED'}`);
                return allowed;
            }

            // Se não é da semana atual nem da próxima, não permitir
            debugLog(`Date outside allowed period - ${dateStr}: CLOSED`);
            return false;
            
        } catch (error) {
            console.error("Erro ao verificar se agendamento é permitido:", error);
            return false;
        }
    }

    function handleSlotClick(event) {
        const cell = event.currentTarget;
        if (cell.classList.contains("booked") || cell.classList.contains("closed")) return;

        const slotDateStr = cell.dataset.date;

        if (!checkIfBookingAllowed(slotDateStr)) {
            showScheduleMessage("Agendamentos estão fechados para esta data (prazo: até quarta-feira 23:59).", "error");
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
        updateButtonStates();
    }

    function updateButtonStates() {
        // Botão "Prosseguir com o agendamento" sempre habilitado (permite apenas observações)
        if (proceedToBookingButton) {
            proceedToBookingButton.disabled = false;
            // Atualizar texto do botão dependendo da situação
            if (selectedSlots.length > 0) {
                proceedToBookingButton.textContent = "Prosseguir com o agendamento";
            } else {
                proceedToBookingButton.textContent = "Fazer agendamento (somente observação)";
            }
        }
        if (generatePdfButton) {
            generatePdfButton.disabled = !currentWeekStartDate;
        }
    }

    function updateSelectedSlotsSummary() {
        if (!selectedSlotsSummaryList) return;
        
        selectedSlotsSummaryList.innerHTML = "";
        
        if (selectedSlots.length === 0) {
            const li = document.createElement("li");
            li.textContent = "Nenhuma sala selecionada - será criado um agendamento apenas com observação";
            li.style.fontStyle = "italic";
            li.style.color = "#666";
            selectedSlotsSummaryList.appendChild(li);
        } else {
            selectedSlots.forEach(slot => {
                const li = document.createElement("li");
                li.textContent = `${slot.roomName} - ${new Date(slot.date + 'T00:00:00Z').toLocaleDateString('pt-BR', {timeZone: 'UTC'})} - ${slot.period}`;
                selectedSlotsSummaryList.appendChild(li);
            });
        }
    }

    // --- PDF Generation (CORRIGIDA) ---
    async function generatePdf() {
        if (!currentWeekStartDate) {
            showScheduleMessage("Carregue uma escala primeiro antes de gerar o PDF.", "error");
            return;
        }

        const startDate = currentWeekStartDate.toISOString().split("T")[0];
        const endDate = new Date(currentWeekStartDate.valueOf());
        endDate.setUTCDate(currentWeekStartDate.getUTCDate() + 4);
        const endDateStr = endDate.toISOString().split("T")[0];

        // Desabilitar o botão durante a geração
        if (generatePdfButton) {
            generatePdfButton.disabled = true;
            generatePdfButton.textContent = "Gerando PDF...";
        }

        showScheduleMessage("Gerando PDF...", "");
        
        try {
            console.log(`Solicitando PDF para período: ${startDate} até ${endDateStr}`);
            
            const response = await fetch(`${API_BASE_URL}/generate-pdf?start_date=${startDate}&end_date=${endDateStr}`, {
                method: 'GET',
                headers: {
                    'Accept': 'application/pdf',
                    'Cache-Control': 'no-cache'
                }
            });
            
            console.log(`Response status: ${response.status}`);
            console.log(`Response headers:`, response.headers);
            
            if (!response.ok) {
                let errorMessage = `Erro ${response.status}: ${response.statusText}`;
                
                try {
                    // Tentar ler como JSON para obter mensagem de erro detalhada
                    const contentType = response.headers.get('content-type');
                    if (contentType && contentType.includes('application/json')) {
                        const errorData = await response.json();
                        errorMessage = errorData.error || errorData.message || errorMessage;
                    } else {
                        // Se não for JSON, ler como texto
                        const errorText = await response.text();
                        if (errorText.trim()) {
                            errorMessage = errorText;
                        }
                    }
                } catch (parseError) {
                    console.error("Erro ao fazer parse da resposta de erro:", parseError);
                }
                
                throw new Error(errorMessage);
            }

            // Verificar se a resposta é realmente um PDF
            const contentType = response.headers.get('content-type');
            if (!contentType || !contentType.includes('application/pdf')) {
                console.warn(`Tipo de conteúdo inesperado: ${contentType}`);
            }

            const blob = await response.blob();
            
            // Verificar se o blob tem conteúdo
            if (blob.size === 0) {
                throw new Error("PDF gerado está vazio");
            }
            
            console.log(`PDF blob criado com tamanho: ${blob.size} bytes`);

            // Criar URL para download
            const url = window.URL.createObjectURL(blob);
            
            // Criar elemento de download
            const a = document.createElement("a");
            a.style.display = "none";
            a.href = url;
            
            // Nome do arquivo com data formatada
            const startDateFormatted = new Date(startDate).toLocaleDateString('pt-BR').replace(/\//g, '-');
            const endDateFormatted = new Date(endDateStr).toLocaleDateString('pt-BR').replace(/\//g, '-');
            a.download = `escala_agendamentos_${startDateFormatted}_a_${endDateFormatted}.pdf`;
            
            // Adicionar ao DOM, clicar e remover
            document.body.appendChild(a);
            a.click();
            
            // Limpar recursos
            window.URL.revokeObjectURL(url);
            document.body.removeChild(a);
            
            showScheduleMessage("PDF gerado e baixado com sucesso!", "success");
            console.log("PDF baixado com sucesso");
            
        } catch (error) {
            console.error("Falha ao gerar PDF:", error);
            
            let userMessage = "Não foi possível gerar o PDF.";
            
            if (error.message.includes('Failed to fetch')) {
                userMessage = "Erro de conexão: Não foi possível conectar ao servidor para gerar o PDF.";
            } else if (error.message.includes('NetworkError')) {
                userMessage = "Erro de rede: Verifique sua conexão com a internet.";
            } else if (error.message.includes('timeout')) {
                userMessage = "Timeout: A geração do PDF demorou muito tempo. Tente novamente.";
            } else if (error.message) {
                userMessage = `Erro: ${error.message}`;
            }
            
            showScheduleMessage(userMessage, "error");
            
        } finally {
            // Re-habilitar o botão
            if (generatePdfButton) {
                generatePdfButton.disabled = false;
                generatePdfButton.textContent = "Gerar PDF";
            }
        }
    }

    // Função auxiliar para debug do endpoint PDF
    async function testPdfEndpoint() {
        if (!currentWeekStartDate) {
            console.error("Nenhuma data de semana definida");
            return;
        }

        const startDate = currentWeekStartDate.toISOString().split("T")[0];
        const endDate = new Date(currentWeekStartDate.valueOf());
        endDate.setUTCDate(currentWeekStartDate.getUTCDate() + 4);
        const endDateStr = endDate.toISOString().split("T")[0];
        
        const testUrl = `${API_BASE_URL}/generate-pdf?start_date=${startDate}&end_date=${endDateStr}`;
        
        console.log("=== TESTE DO ENDPOINT PDF ===");
        console.log(`URL: ${testUrl}`);
        console.log(`Período: ${startDate} até ${endDateStr}`);
        
        try {
            const response = await fetch(testUrl, {
                method: 'HEAD' // Usar HEAD para testar sem baixar o conteúdo
            });
            
            console.log(`Status: ${response.status}`);
            console.log(`Status Text: ${response.statusText}`);
            console.log(`Headers:`, [...response.headers.entries()]);
            
            if (response.ok) {
                console.log("✅ Endpoint PDF está respondendo corretamente");
            } else {
                console.log("❌ Endpoint PDF retornou erro");
            }
            
        } catch (error) {
            console.error("❌ Erro ao testar endpoint PDF:", error);
        }
    }

    // --- Booking Creation ---
    async function createBooking(formData) {
        console.log("=== DEBUG: Iniciando createBooking ===");
        
        // Debug: Listar todos os campos do FormData
        console.log("Campos do FormData:");
        for (let [key, value] of formData.entries()) {
            console.log(`  ${key}: "${value}"`);
        }

        const userName = formData.get("userName");
        const userEmail = formData.get("userEmail");
        const coordinatorName = formData.get("coordinatorName") || "";
        const observation = formData.get("observation") || "";

        console.log("Valores extraídos:");
        console.log(`  userName: "${userName}"`);
        console.log(`  userEmail: "${userEmail}"`);
        console.log(`  coordinatorName: "${coordinatorName}"`);
        console.log(`  observation: "${observation}"`);
        console.log(`  selectedSlots: ${selectedSlots.length} slots`);

        // Validação de campos obrigatórios no frontend
        if (!userName || userName.trim() === "") {
            showModalMessage("Nome é obrigatório para o agendamento.", "error");
            return;
        }

        if (!userEmail || userEmail.trim() === "") {
            showModalMessage("E-mail é obrigatório para o agendamento.", "error");
            return;
        }

        // Validação de formato de e-mail no frontend
        const emailTrimmed = userEmail.trim();
        if (!emailTrimmed.includes("@") || !emailTrimmed.includes(".")) {
            showModalMessage("Por favor, insira um e-mail válido.", "error");
            return;
        }

        // REMOVIDA A VALIDAÇÃO QUE IMPEDIA AGENDAMENTOS SEM SLOTS
        // Agora permite agendamentos somente com observação
        if (selectedSlots.length === 0 && !observation.trim()) {
            showModalMessage("É necessário fornecer uma observação quando não há salas selecionadas (ex: solicitação de encaixe).", "error");
            return;
        }

        const bookingData = {
            // MODIFICAÇÃO: Enviar 'period' diretamente, sem conversão
            slots: selectedSlots.map(slot => ({
                room_id: slot.roomId,
                booking_date: slot.date,
                period: slot.period // Usando 'period' diretamente
            })),
            user_name: userName.trim(),
            user_email: emailTrimmed,
            coordinator_name: coordinatorName.trim(),
            observation: observation.trim()
        };

        console.log("=== DEBUG: Dados finais do agendamento ===");
        console.log(JSON.stringify(bookingData, null, 2));
        console.log(`URL da requisição: ${API_BASE_URL}/bookings`);

        // Mostrar mensagem diferente para agendamentos somente observação
        if (selectedSlots.length === 0) {
            showModalMessage("Enviando solicitação de encaixe...", "");
        } else {
            showModalMessage("Enviando agendamento...", "");
        }

        try {
            console.log("=== DEBUG: Fazendo requisição POST ===");
            const response = await fetch(`${API_BASE_URL}/bookings`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify(bookingData)
            });

            console.log(`=== DEBUG: Response Status: ${response.status} ===`);
            console.log(`=== DEBUG: Response OK: ${response.ok} ===`);

            let result;
            try {
                result = await response.json();
                console.log("=== DEBUG: Response JSON ===");
                console.log(JSON.stringify(result, null, 2));
            } catch (jsonError) {
                console.error("=== DEBUG: Erro ao fazer parse do JSON ===", jsonError);
                const textResponse = await response.text();
                console.log("=== DEBUG: Response Text ===", textResponse);
                throw new Error(`Resposta inválida do servidor (Status: ${response.status})`);
            }

            if (response.ok) {
                if (selectedSlots.length === 0) {
                    showModalMessage("Solicitação de encaixe registrada com sucesso!", "success");
                } else {
                    showModalMessage("Agendamento realizado com sucesso!", "success");
                }
                
                // Limpar slots selecionados e atualizar a tabela após o sucesso
                selectedSlots.forEach(slot => {
                    if (slot.cellRef) {
                        slot.cellRef.classList.remove("selected");
                        slot.cellRef.classList.add("booked");
                        slot.cellRef.textContent = userName.trim();
                        slot.cellRef.removeEventListener("click", handleSlotClick);
                        slot.cellRef.style.cursor = "default";
                        slot.cellRef.title = `Reservado por: ${userName.trim()}`;
                    }
                });
                
                selectedSlots = [];
                updateSelectedSlotsSummary();
                updateButtonStates(); // Atualizar texto do botão
                modalBookingForm.reset();
                // Recarregar a escala para garantir consistência
                setTimeout(() => {
                    loadScheduleData(currentWeekStartDate.toISOString().split("T")[0]);
                }, 1000);
                
            } else {
                // Tratar diferentes tipos de erro do servidor
                let errorMessage = "Erro desconhecido do servidor";
                
                if (result && result.error) {
                    errorMessage = result.error;
                } else if (result && result.message) {
                    errorMessage = result.message;
                } else if (result && result.detail) {
                    errorMessage = result.detail;
                } else {
                    errorMessage = `Erro ${response.status}: ${response.statusText}`;
                }
                
                console.error("=== DEBUG: Erro do servidor ===", {
                    status: response.status,
                    statusText: response.statusText,
                    result: result,
                    errorMessage: errorMessage
                });
                
                showModalMessage(`Falha ao criar agendamento: ${errorMessage}`, "error");
            }
        } catch (error) {
            console.error("=== DEBUG: Erro na requisição ===", error)
            
            if (error.name === 'TypeError' && error.message.includes('fetch')) {
                showModalMessage("Erro de conexão: Não foi possível conectar ao servidor. Verifique sua conexão.", "error");
            } else if (error.message.includes('JSON')) {
                showModalMessage("Erro de comunicação: Resposta inválida do servidor.", "error");
            } else {
                showModalMessage(`Erro de conexão: ${error.message}`, "error");
            }
        }
    }

    // --- Modal and Form Handling ---
    if (proceedToBookingButton) {
        proceedToBookingButton.addEventListener("click", () => {
            updateSelectedSlotsSummary();
            bookingModal.style.display = "block";
            
            // Focar no campo de observação se não há slots selecionados
            if (selectedSlots.length === 0) {
                setTimeout(() => {
                    const observationField = document.querySelector('#modalBookingForm textarea[name="observation"]');
                    if (observationField) {
                        observationField.focus();
                        observationField.placeholder = "Descreva sua solicitação de encaixe (ex: 'Preciso de uma sala na sexta à tarde para reunião urgente')";
                    }
                }, 100);
            }
        });
    }

    if (closeModalButton) {
        closeModalButton.addEventListener("click", () => {
            bookingModal.style.display = "none";
            if (modalFormMessage) {
                modalFormMessage.textContent = "";
                modalFormMessage.className = "message";
            }
        });
    }

    window.addEventListener("click", (event) => {
        if (event.target === bookingModal) {
            bookingModal.style.display = "none";
            if (modalFormMessage) {
                modalFormMessage.textContent = "";
                modalFormMessage.className = "message";
            }
        }
    });

    if (modalBookingForm) {
        modalBookingForm.addEventListener("submit", async (event) => {
            event.preventDefault();
            console.log("=== DEBUG: Form submit ===");
            
            // Debug: Verificar se o formulário existe e tem elementos
            console.log("Form encontrado:", modalBookingForm);
            console.log("
