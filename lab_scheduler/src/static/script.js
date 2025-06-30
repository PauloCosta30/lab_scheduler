// /home/ubuntu/lab_scheduler/src/static/script.js

document.addEventListener("DOMContentLoaded", () => {
    // DOM Elements for Modal and New Flow
    const scheduleTableContainer = document.getElementById("scheduleTableContainer");
    const scheduleMessage = document.getElementById("scheduleMessage");
    const proceedToBookingButton = document.getElementById("proceedToBookingButton");
    const generatePdfButton = document.getElementById("generatePdfButton");
    const weekSelector = document.getElementById("weekSelector"); // ADICIONADO - estava faltando
    const loadScheduleButton = document.getElementById("loadScheduleButton"); // ADICIONADO - estava faltando

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
            return true;
        } catch (error) {
            console.error("Falha ao buscar status da janela de agendamento:", error);
            showBookingStatusMessage("Não foi possível verificar o status do agendamento", "error");
            return false;
        }
    }

    function updateBookingStatusDisplay() {
        if (!bookingWindowStatus) return;

        showBookingStatusMessage("As escolhas para a semana atual sempre serão encerradas às quartas-feiras, às 18h, e a escala da próxima semana será liberada todas as sextas-feiras, às 18h.", "info");

        // Ocultar os status individuais da semana atual e próxima semana, pois a mensagem é fixa
        if (currentWeekStatus) currentWeekStatus.style.display = "none";
        if (nextWeekStatus) nextWeekStatus.style.display = "none";
    }

    // --- Room Data --- 
    async function fetchAllRooms() {
        try {
            const response = await fetch(`${API_BASE_URL}/rooms`);
            if (!response.ok) {
                throw new Error(`Erro ao buscar salas: ${response.statusText}`);
            }
            allRooms = await response.json();
            console.log(`Carregadas ${allRooms.length} salas`);
            return true;
        } catch (error) {
            console.error("Falha ao buscar salas:", error);
            showScheduleMessage("Não foi possível carregar dados das salas. Tente recarregar.", "error");
            return false;
        }
    }

    // --- Schedule Logic (Loading and Rendering) ---
    async function loadScheduleData(inputDate = null) { // CORRIGIDO - aceita parâmetro
        let startDate, endDate;
        const todayUTC = getTodayUTC();

        try {
            let referenceDate;
            if (inputDate) {
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
            
            const response = await fetch(`${API_BASE_URL}/bookings?start_date=${startDateStrAPI}&end_date=${endDateStrAPI}`);
            if (!response.ok) {
                throw new Error(`Erro ao buscar agendamentos: ${response.statusText}`);
            }
            currentFetchedBookings = await response.json();
            console.log(`Carregados ${currentFetchedBookings.length} agendamentos`);
            
            // Verificar se temos as salas carregadas
            if (allRooms.length === 0) {
                const roomsLoaded = await fetchAllRooms();
                if (!roomsLoaded) {
                    throw new Error("Não foi possível carregar as salas");
                }
            }
            
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
        if (!scheduleTableContainer) {
            console.error("scheduleTableContainer não encontrado");
            return;
        }

        scheduleTableContainer.innerHTML = "";
        selectedSlots = [];
        updateButtonStates();
        const todayUTC = getTodayUTC();

        const table = document.createElement("table");
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
            row.appendChild(roomCell);

            datesOfWeek.forEach(dateStr => {
                const slotDateUTC = parseDateStrToUTC(dateStr);
                const isPastDate = slotDateUTC < todayUTC;

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
                    } else if (isPastDate) {
                        cell.textContent = "Indisponível";
                        cell.classList.add("past");
                    } else {
                        // Verificar se o agendamento está permitido para esta data
                        const isBookingAllowed = checkIfBookingAllowed(dateStr);
                        if (isBookingAllowed) {
                            cell.textContent = "Disponível";
                            cell.classList.add("available");
                            cell.dataset.roomId = room.id;
                            cell.dataset.roomName = room.name;
                            cell.dataset.date = dateStr;
                            cell.dataset.period = period;
                            cell.addEventListener("click", handleSlotClick);
                        } else {
                            cell.textContent = "Fechado";
                            cell.classList.add("closed");
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

        try {
            const slotDate = parseDateStrToUTC(dateStr);
            const now = new Date(); // Hora atual no Brasil
            const today = getTodayUTC();
            
            // Calcular segunda-feira da semana atual
            const currentWeekMonday = new Date(today.valueOf());
            const dayOffset = today.getUTCDay() === 0 ? 6 : today.getUTCDay() - 1;
            currentWeekMonday.setUTCDate(today.getUTCDate() - dayOffset);
            
            const nextWeekMonday = new Date(currentWeekMonday.getTime() + 7 * 24 * 60 * 60 * 1000);

            // Verificar se o slot é da semana atual
            if (slotDate >= currentWeekMonday && slotDate < nextWeekMonday) {
                // Para semana atual: disponível até quarta-feira às 18h
                const currentDayOfWeek = now.getDay(); // 0=domingo, 1=segunda, ..., 6=sábado
                const currentHour = now.getHours();
                
                // Se hoje é quarta-feira (3) e já passou das 18h, ou se já é quinta/sexta/sábado/domingo
                if ((currentDayOfWeek === 3 && currentHour >= 18) || currentDayOfWeek > 3 || currentDayOfWeek === 0) {
                    return false; // Fechado para semana atual
                }
                
                return bookingWindowStatus.current_week.open;
                
            } else if (slotDate >= nextWeekMonday && slotDate < new Date(nextWeekMonday.getTime() + 7 * 24 * 60 * 60 * 1000)) {
                // Para próxima semana: disponível a partir de sexta-feira às 18h
                const currentDayOfWeek = now.getDay();
                const currentHour = now.getHours();
                
                // Só aberto se já é sexta-feira (5) após 18h, ou se é sábado/domingo
                if (currentDayOfWeek === 5 && currentHour >= 18) {
                    return bookingWindowStatus.next_week.open; // Sexta após 18h
                } else if (currentDayOfWeek === 6 || currentDayOfWeek === 0) {
                    return bookingWindowStatus.next_week.open; // Sábado ou domingo
                } else {
                    return false; // Ainda não abriu
                }
            }

            return false;
        } catch (error) {
            console.error("Erro ao verificar se agendamento é permitido:", error);
            return false;
        }
    }

    function handleSlotClick(event) {
        const cell = event.currentTarget;
        if (cell.classList.contains("booked") || cell.classList.contains("past") || cell.classList.contains("closed")) return;

        const slotDateStr = cell.dataset.date;
        const slotDateUTC = parseDateStrToUTC(slotDateStr);
        const todayUTC = getTodayUTC();

        if (slotDateUTC < todayUTC) {
            showScheduleMessage("Não é possível selecionar datas/horários passados.", "error");
            return;
        }

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
        if (proceedToBookingButton) {
            proceedToBookingButton.disabled = selectedSlots.length === 0; // CORRIGIDO
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

        showScheduleMessage("Gerando PDF...", "");
        
        try {
            const response = await fetch(`${API_BASE_URL}/generate-pdf?start_date=${startDate}&end_date=${endDateStr}`);
            
            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.error || "Erro ao gerar PDF");
            }

            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.style.display = 'none';
            a.href = url;
            a.download = `escala_agendamentos_${startDate}_a_${endDateStr}.pdf`;
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
            document.body.removeChild(a);
            
            showScheduleMessage("PDF gerado e baixado com sucesso!", "success");
        } catch (error) {
            console.error("Erro ao gerar PDF:", error);
            showScheduleMessage(`Erro ao gerar PDF: ${error.message}`, "error");
        }
    }

    // --- Modal Logic ---
    function openBookingModal() {
        if (selectedSlots.length === 0) {
            showScheduleMessage("Nenhum horário selecionado.", "error");
            return;
        }

        const todayUTC = getTodayUTC();
        for (const slot of selectedSlots) {
            if (parseDateStrToUTC(slot.date) < todayUTC) {
                showScheduleMessage("Um ou mais horários selecionados estão no passado e não podem ser agendados. Por favor, desmarque-os.", "error");
                return;
            }
            if (!checkIfBookingAllowed(slot.date)) {
                showScheduleMessage("Um ou mais horários selecionados estão fora da janela de agendamento.", "error");
                return;
            }
        }

        if (selectedSlotsSummaryList) {
            selectedSlotsSummaryList.innerHTML = "";
            selectedSlots.forEach(slot => {
                const li = document.createElement("li");
                li.textContent = `${slot.roomName} - ${new Date(slot.date + 'T00:00:00').toLocaleDateString('pt-BR', {timeZone: 'UTC'})} - ${slot.period}`;
                selectedSlotsSummaryList.appendChild(li);
            });
        }
        
        if (modalBookingForm) {
            modalBookingForm.reset();
        }
        showModalMessage("", "");
        if (bookingModal) {
            bookingModal.style.display = "block";
        }
    }

    function closeBookingModal() {
        if (bookingModal) {
            bookingModal.style.display = "none";
        }
    }

    async function handleModalFormSubmit(event) {
        event.preventDefault();
        if (!modalBookingForm) return;

        const formData = new FormData(modalBookingForm);
        const requestData = {
            user_name: formData.get("userName"),
            user_email: formData.get("userEmail"),
            coordinator_name: formData.get("coordinatorName"),
            observation: formData.get("observation") || "",
            slots: selectedSlots.map(s => ({ 
                room_id: s.roomId, 
                booking_date: s.date, 
                period: s.period 
            }))
        };

        if (requestData.slots.length === 0) {
            showModalMessage("Nenhum horário foi selecionado para agendar.", "error");
            return; // CORRIGIDO - removido console.warn
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
                selectedSlots.forEach(slot => {
                    if (slot.cellRef) {
                        slot.cellRef.classList.remove('selected', 'available');
                        slot.cellRef.classList.add('booked');
                        slot.cellRef.textContent = requestData.user_name;
                        slot.cellRef.removeEventListener('click', handleSlotClick);
                    }
                });
                selectedSlots = [];
                updateButtonStates();
                setTimeout(() => {
                    closeBookingModal();
                    loadScheduleData(); // CORRIGIDO - parâmetro removido
                }, 2000);
            } else {
                showModalMessage(result.error || "Erro ao realizar agendamento.", "error");
            }
        } catch (error) {
            console.error("Erro ao submeter agendamento do modal:", error);
            showModalMessage("Falha na comunicação com o servidor. Tente novamente.", "error");
        }
    }

    // --- Event Listeners ---
    if (loadScheduleButton) {
        loadScheduleButton.addEventListener("click", () => {
            const selectedDate = weekSelector ? weekSelector.value : null;
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

    if (generatePdfButton) {
        generatePdfButton.addEventListener("click", generatePdf);
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

    // --- Initializations ---
    async function initializeApp() {
        try {
            const todayUTC = getTodayUTC();
            const todayUTCStr = todayUTC.toISOString().split("T")[0];
            
            if (weekSelector) {
                weekSelector.value = todayUTCStr;
                weekSelector.min = todayUTCStr;
            }
            
            console.log("Inicializando aplicação...");
            
            // Carregar status da janela de agendamento
            console.log("Carregando status da janela de agendamento...");
            const statusLoaded = await fetchBookingWindowStatus();
            
            // Carregar salas
            console.log("Carregando salas...");
            const roomsLoaded = await fetchAllRooms();
            
            // Só carregar a escala se o status e as salas foram carregados com sucesso
            if (statusLoaded && roomsLoaded) {
                console.log("Carregando escala inicial...");
                await loadScheduleData();
            } else {
                throw new Error("Falha ao carregar dados iniciais");
            }
            
            // Atualizar status a cada 5 minutos
            setInterval(fetchBookingWindowStatus, 5 * 60 * 1000);
            
            console.log("Aplicação inicializada com sucesso!");
            
        } catch (error) {
            console.error("Erro durante a inicialização:", error);
            showScheduleMessage("Erro durante a inicialização da aplicação", "error");
        }
    }

    initializeApp();

});
