document.addEventListener("DOMContentLoaded", () => {
    // DOM Elements
    const scheduleTableContainer = document.getElementById("scheduleTableContainer");
    const scheduleMessage = document.getElementById("scheduleMessage");
    const proceedToBookingButton = document.getElementById("proceedToBookingButton");
    const generatePdfButton = document.getElementById("generatePdfButton");
    const weekSelector = document.getElementById("weekSelector");
    const loadScheduleButton = document.getElementById("loadScheduleButton");
    const bookingStatusMessage = document.getElementById("bookingStatusMessage");
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

    // --- Helper Functions for Date Handling ---
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

    // --- Week Display Logic (CORRIGIDA) ---
    function getWeekToDisplay() {
        const now = new Date(); // Usa o horário local do navegador do usuário
        const currentDayOfWeek = now.getDay(); // 0=Domingo, 1=Segunda, ..., 6=Sábado
        const currentHour = now.getHours();
        
        console.log(`=== DETERMINANDO SEMANA PARA EXIBIR ===`);
        console.log(`Dia da semana local: ${currentDayOfWeek} (0=Dom, 1=Seg, ..., 6=Sab)`);
        console.log(`Hora local: ${currentHour}:${now.getMinutes().toString().padStart(2, '0')}`);
        
        // REGRA CORRIGIDA:
        // A próxima semana só deve ser exibida a partir de quinta-feira (4) às 18:00.
        if ( (currentDayOfWeek === 4 && currentHour >= 18) || // Quinta-feira a partir das 18h
             currentDayOfWeek === 5 ||                          // Sexta-feira
             currentDayOfWeek === 6 ||                          // Sábado
             currentDayOfWeek === 0 ) {                         // Domingo
            
            const nextWeek = new Date(now);
            // Lógica para pular para a próxima segunda-feira
            const daysToAdd = (8 - currentDayOfWeek) % 7;
            nextWeek.setDate(now.getDate() + (daysToAdd === 0 ? 7 : daysToAdd));
            
            const nextWeekDate = nextWeek.toISOString().split("T")[0];
            
            console.log(`DECISÃO: EXIBIR PRÓXIMA SEMANA (iniciando em ${nextWeekDate})`);
            return nextWeekDate;
        }
        
        // Em todos os outros casos (de segunda até quinta antes das 18h), mostrar a semana atual.
        console.log(`DECISÃO: EXIBIR SEMANA ATUAL`);
        return null; // null indica para a função loadScheduleData usar a semana atual
    }

    // --- Booking Window Status Functions ---
    async function fetchBookingWindowStatus() {
        try {
            const response = await fetch(`${API_BASE_URL}/booking-window-status`);
            if (response.ok) {
                bookingWindowStatus = await response.json();
                console.log("Status da janela de agendamento carregado do servidor:", bookingWindowStatus);
            } else {
                throw new Error("Servidor não disponível para status");
            }
        } catch (error) {
            console.warn("Falha ao buscar status do servidor:", error);
            showBookingStatusMessage("Não foi possível verificar o status do agendamento. A funcionalidade pode ser limitada.", "error");
        }
        
        updateBookingStatusDisplay();
        return true;
    }

    function updateBookingStatusDisplay() {
        if (!bookingWindowStatus) return;
        const message = bookingWindowStatus.general_message || "Verificando status do agendamento...";
        showBookingStatusMessage(message, "info");
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
            console.log(`Carregadas ${allRooms.length} salas.`);
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
        
        try {
            let referenceDate;
            
            if (inputDate) {
                referenceDate = parseDateStrToUTC(inputDate);
            } else {
                const weekToDisplay = getWeekToDisplay();
                if (weekToDisplay) {
                    referenceDate = parseDateStrToUTC(weekToDisplay);
                } else {
                    referenceDate = getTodayUTC();
                }
            }

            const dayOfWeek = referenceDate.getUTCDay();
            const diffToMonday = dayOfWeek === 0 ? -6 : 1 - dayOfWeek;
            const startDate = new Date(referenceDate.valueOf());
            startDate.setUTCDate(referenceDate.getUTCDate() + diffToMonday);
            
            currentWeekStartDate = startDate;

            const startDateStrAPI = startDate.toISOString().split("T")[0];
            const endDate = new Date(startDate.valueOf());
            endDate.setUTCDate(startDate.getUTCDate() + 4);
            const endDateStrAPI = endDate.toISOString().split("T")[0];
            
            showScheduleMessage("Carregando escala...", "");
            
            if (allRooms.length === 0) {
                const roomsLoaded = await fetchAllRooms();
                if (!roomsLoaded) throw new Error("Não foi possível carregar as salas");
            }
            
            const response = await fetch(`${API_BASE_URL}/bookings?start_date=${startDateStrAPI}&end_date=${endDateStrAPI}`);
            if (!response.ok) throw new Error(`Erro ao buscar agendamentos: ${response.statusText}`);
            
            currentFetchedBookings = await response.json();
            renderScheduleTable(currentFetchedBookings, allRooms, currentWeekStartDate);
            showScheduleMessage("Escala carregada.", "success");
            
        } catch (error) {
            console.error("Falha ao carregar escala:", error);
            showScheduleMessage(`Não foi possível carregar a escala: ${error.message}`, "error");
            if (scheduleTableContainer) scheduleTableContainer.innerHTML = "<p>Erro ao carregar escala.</p>";
        }
    }

    function renderScheduleTable(bookings, roomsData, weekStartDateObj) {
        if (!scheduleTableContainer || !roomsData || roomsData.length === 0 || !weekStartDateObj) {
            scheduleTableContainer.innerHTML = "<p>Erro ao renderizar a escala. Dados insuficientes.</p>";
            return;
        }

        scheduleTableContainer.innerHTML = "";
        selectedSlots = [];
        updateButtonStates();

        const infoDiv = document.createElement("div");
        infoDiv.className = "booking-info";
        infoDiv.style.cssText = "background: #e8f4fd; border: 1px solid #bee5eb; padding: 10px; margin-bottom: 15px; border-radius: 4px; color: #0c5460;";
        infoDiv.innerHTML = `<strong>💡 Dica:</strong> Se todas as salas estiverem ocupadas, você pode fazer um agendamento apenas com observação para solicitar encaixe. Clique em "Prosseguir com o agendamento" mesmo sem selecionar nenhuma sala.`;
        scheduleTableContainer.appendChild(infoDiv);

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
    }

    function checkIfBookingAllowed(dateStr) {
        if (!bookingWindowStatus) return false;

        const slotDate = parseDateStrToUTC(dateStr);
        const todayUTC = getTodayUTC();
        
        const currentWeekMonday = new Date(todayUTC.valueOf());
        const dayOffset = todayUTC.getUTCDay() === 0 ? 6 : todayUTC.getUTCDay() - 1;
        currentWeekMonday.setUTCDate(todayUTC.getUTCDate() - dayOffset);
        
        const nextWeekMonday = new Date(currentWeekMonday.getTime() + 7 * 24 * 60 * 60 * 1000);

        if (slotDate >= currentWeekMonday && slotDate < nextWeekMonday) {
            return bookingWindowStatus.current_week.open;
        } else if (slotDate >= nextWeekMonday && slotDate < new Date(nextWeekMonday.getTime() + 7 * 24 * 60 * 60 * 1000)) {
            return bookingWindowStatus.next_week.open;
        }
        return false;
    }

    function handleSlotClick(event) {
        const cell = event.currentTarget;
        if (cell.classList.contains("booked") || cell.classList.contains("closed")) return;

        const slotDateStr = cell.dataset.date;
        if (!checkIfBookingAllowed(slotDateStr)) {
            showScheduleMessage("Agendamentos estão fechados para esta data.", "error");
            return;
        }

        const slotData = {
            roomId: parseInt(cell.dataset.roomId),
            roomName: cell.dataset.roomName,
            date: slotDateStr,
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
        if (proceedToBookingButton) {
            proceedToBookingButton.disabled = false;
            proceedToBookingButton.textContent = selectedSlots.length > 0 ? "Prosseguir com o agendamento" : "Fazer agendamento (somente observação)";
        }
        if (generatePdfButton) {
            generatePdfButton.disabled = !currentWeekStartDate;
        }
    }

    // --- PDF Generation ---
    async function generatePdf() {
        if (!currentWeekStartDate) {
            showScheduleMessage("Carregue uma escala primeiro antes de gerar o PDF.", "error");
            return;
        }

        const startDate = currentWeekStartDate.toISOString().split("T")[0];
        const endDate = new Date(currentWeekStartDate.valueOf());
        endDate.setUTCDate(currentWeekStartDate.getUTCDate() + 4);
        const endDateStr = endDate.toISOString().split("T")[0];

        if (generatePdfButton) {
            generatePdfButton.disabled = true;
            generatePdfButton.textContent = "Gerando PDF...";
        }
        showScheduleMessage("Gerando PDF...", "");
        
        try {
            const response = await fetch(`${API_BASE_URL}/generate-pdf?start_date=${startDate}&end_date=${endDateStr}`);
            if (!response.ok) {
                const errorData = await response.json().catch(() => ({ error: `Erro ${response.status}` }));
                throw new Error(errorData.error || errorData.message);
            }

            const blob = await response.blob();
            if (blob.size === 0) throw new Error("PDF gerado está vazio");

            const url = window.URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.style.display = "none";
            a.href = url;
            a.download = `escala_agendamentos_${startDate}_a_${endDateStr}.pdf`;
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
            document.body.removeChild(a);
            showScheduleMessage("PDF gerado e baixado com sucesso!", "success");
            
        } catch (error) {
            console.error("Falha ao gerar PDF:", error);
            showScheduleMessage(`Erro ao gerar PDF: ${error.message}`, "error");
        } finally {
            if (generatePdfButton) {
                generatePdfButton.disabled = false;
                generatePdfButton.textContent = "Gerar PDF";
            }
        }
    }

    // --- Booking Creation ---
    async function createBooking(formData) {
        const userName = formData.get("userName");
        const userEmail = formData.get("userEmail");
        const coordinatorName = formData.get("coordinatorName") || "";
        const observation = formData.get("observation") || "";

        if (!userName || !userEmail) {
            showModalMessage("Nome e E-mail são obrigatórios.", "error");
            return;
        }
        if (selectedSlots.length === 0 && !observation.trim()) {
            showModalMessage("É necessário fornecer uma observação quando não há salas selecionadas.", "error");
            return;
        }

        const bookingData = {
            user_name: userName.trim(),
            user_email: userEmail.trim(),
            coordinator_name: coordinatorName.trim(),
            observation: observation.trim(),
            slots: selectedSlots.map(slot => ({
                room_id: slot.roomId,
                booking_date: slot.date,
                period: slot.period
            }))
        };

        showModalMessage("Enviando agendamento...", "");

        try {
            const response = await fetch(`${API_BASE_URL}/bookings`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(bookingData)
            });

            const result = await response.json();
            if (response.ok) {
                showModalMessage("Agendamento realizado com sucesso!", "success");
                modalBookingForm.reset();
                setTimeout(() => {
                    bookingModal.style.display = "none";
                    loadScheduleData(currentWeekStartDate.toISOString().split("T")[0]);
                }, 2000);
            } else {
                throw new Error(result.error || "Erro desconhecido do servidor");
            }
        } catch (error) {
            showModalMessage(`Falha ao criar agendamento: ${error.message}`, "error");
        }
    }

    // --- Modal and Form Handling ---
    if (proceedToBookingButton) {
        proceedToBookingButton.addEventListener("click", () => {
            updateSelectedSlotsSummary();
            bookingModal.style.display = "block";
        });
    }

    if (closeModalButton) {
        closeModalButton.addEventListener("click", () => {
            bookingModal.style.display = "none";
        });
    }

    window.addEventListener("click", (event) => {
        if (event.target === bookingModal) {
            bookingModal.style.display = "none";
        }
    });

    if (modalBookingForm) {
        modalBookingForm.addEventListener("submit", (event) => {
            event.preventDefault();
            const formData = new FormData(modalBookingForm);
            createBooking(formData);
        });
    }

    function updateSelectedSlotsSummary() {
        if (!selectedSlotsSummaryList) return;
        selectedSlotsSummaryList.innerHTML = "";
        if (selectedSlots.length === 0) {
            const li = document.createElement("li");
            li.innerHTML = "<em>Nenhum horário selecionado - Agendamento somente observação</em>";
            selectedSlotsSummaryList.appendChild(li);
            return;
        }
        selectedSlots.forEach(slot => {
            const li = document.createElement("li");
            li.textContent = `${slot.roomName} - ${slot.date} - ${slot.period}`;
            selectedSlotsSummaryList.appendChild(li);
        });
    }

    // --- Event Listeners ---
    if (weekSelector) {
        weekSelector.value = new Date().toISOString().split("T")[0];
    }
    
    if (loadScheduleButton) {
        loadScheduleButton.addEventListener("click", () => {
            const selectedDate = weekSelector ? weekSelector.value : null;
            loadScheduleData(selectedDate);
        });
    }
    
    if (generatePdfButton) {
        generatePdfButton.addEventListener("click", generatePdf);
    }

    // --- Initialization ---
    console.log("Inicializando aplicação...");
    fetchBookingWindowStatus().then(() => {
        loadScheduleData();
    });
});
