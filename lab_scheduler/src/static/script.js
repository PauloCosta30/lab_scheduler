document.addEventListener("DOMContentLoaded", () => {
    // --- MODIFICADO: Adicionar novos botões de navegação ---
    const scheduleTableContainer = document.getElementById("scheduleTableContainer");
    const scheduleMessage = document.getElementById("scheduleMessage");
    const proceedToBookingButton = document.getElementById("proceedToBookingButton");
    const generatePdfButton = document.getElementById("generatePdfButton");
    const weekSelector = document.getElementById("weekSelector");
    const loadScheduleButton = document.getElementById("loadScheduleButton");
    const prevWeekButton = document.getElementById("prevWeekButton"); // NOVO
    const nextWeekButton = document.getElementById("nextWeekButton"); // NOVO
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
    let currentWeekStartDate; // Esta variável agora é a chave para a navegação
    let bookingWindowStatus = null;

    // --- Funções Helper (sem alteração) ---
    function getTodayUTC() {
        const today = new Date();
        return new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate()));
    }

    function parseDateStrToUTC(dateStr) {
        const [year, month, day] = dateStr.split("-").map(Number);
        return new Date(Date.UTC(year, month - 1, day));
    }

    function showModalMessage(message, type) { /* ...código sem alteração... */ }
    function showScheduleMessage(message, type) { /* ...código sem alteração... */ }
    function showBookingStatusMessage(message, type) { /* ...código sem alteração... */ }

    // --- Lógica de Exibição da Semana (sem alteração) ---
    function getWeekToDisplay() {
        // Esta função continua definindo a semana padrão no primeiro carregamento
        const now = new Date();
        const currentDayOfWeek = now.getDay();
        const currentHour = now.getHours();
        
        if ( (currentDayOfWeek === 4 && currentHour >= 18) || currentDayOfWeek >= 5 || currentDayOfWeek === 0 ) {
            const nextWeek = new Date(now);
            const daysToAdd = (8 - currentDayOfWeek) % 7;
            nextWeek.setDate(now.getDate() + (daysToAdd === 0 ? 7 : daysToAdd));
            return nextWeek.toISOString().split("T")[0];
        }
        return null;
    }

    // --- Funções de Status e Salas (sem alteração) ---
    async function fetchBookingWindowStatus() { /* ...código sem alteração... */ }
    function updateBookingStatusDisplay() { /* ...código sem alteração... */ }
    async function fetchAllRooms() { /* ...código sem alteração... */ }

    // --- Lógica de Carregamento da Escala (MODIFICADA) ---
    async function loadScheduleData(inputDateStr = null) {
        console.log(`Iniciando carregamento da escala. Data de entrada: ${inputDateStr}`);
        
        try {
            let referenceDate;
            
            if (inputDateStr) {
                // Se uma data foi fornecida (pelo seletor ou botões), use-a
                referenceDate = parseDateStrToUTC(inputDateStr);
            } else {
                // Se nenhuma data foi fornecida (primeiro carregamento), use a lógica padrão
                const weekToDisplay = getWeekToDisplay();
                if (weekToDisplay) {
                    referenceDate = parseDateStrToUTC(weekToDisplay);
                } else {
                    referenceDate = getTodayUTC();
                }
            }

            // Calcula a segunda-feira da semana de referência
            const dayOfWeek = referenceDate.getUTCDay();
            const diffToMonday = dayOfWeek === 0 ? -6 : 1 - dayOfWeek;
            const startDate = new Date(referenceDate.valueOf());
            startDate.setUTCDate(referenceDate.getUTCDate() + diffToMonday);
            
            // ATUALIZA A DATA GLOBAL, que é a nossa "fonte da verdade" para a navegação
            currentWeekStartDate = startDate;

            // --- NOVA LÓGICA: Atualiza o valor do seletor de data ---
            if (weekSelector) {
                weekSelector.value = currentWeekStartDate.toISOString().split("T")[0];
            }

            const startDateStrAPI = currentWeekStartDate.toISOString().split("T")[0];
            const endDate = new Date(currentWeekStartDate.valueOf());
            endDate.setUTCDate(currentWeekStartDate.getUTCDate() + 4);
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

    // --- Funções de Renderização e Agendamento (sem alteração) ---
    function renderScheduleTable(bookings, roomsData, weekStartDateObj) { /* ...código sem alteração... */ }
    function checkIfBookingAllowed(dateStr) { /* ...código sem alteração... */ }
    function handleSlotClick(event) { /* ...código sem alteração... */ }
    function updateButtonStates() { /* ...código sem alteração... */ }
    async function generatePdf() { /* ...código sem alteração... */ }
    async function createBooking(formData) { /* ...código sem alteração... */ }
    function updateSelectedSlotsSummary() { /* ...código sem alteração... */ }

    // --- Modal and Form Handling (sem alteração) ---
    if (proceedToBookingButton) { /* ...código sem alteração... */ }
    if (closeModalButton) { /* ...código sem alteração... */ }
    window.addEventListener("click", (event) => { /* ...código sem alteração... */ });
    if (modalBookingForm) { /* ...código sem alteração... */ }

    // --- Event Listeners (MODIFICADO) ---
    if (loadScheduleButton) {
        loadScheduleButton.addEventListener("click", () => {
            const selectedDate = weekSelector ? weekSelector.value : null;
            if (selectedDate) {
                loadScheduleData(selectedDate);
            } else {
                showScheduleMessage("Por favor, selecione uma data.", "error");
            }
        });
    }

    // --- NOVA LÓGICA: Event Listeners para os botões de navegação ---
    if (prevWeekButton) {
        prevWeekButton.addEventListener("click", () => {
            if (currentWeekStartDate) {
                // Pega a data da semana atual e subtrai 7 dias
                const prevWeekDate = new Date(currentWeekStartDate.valueOf());
                prevWeekDate.setUTCDate(currentWeekStartDate.getUTCDate() - 7);
                loadScheduleData(prevWeekDate.toISOString().split("T")[0]);
            }
        });
    }

    if (nextWeekButton) {
        nextWeekButton.addEventListener("click", () => {
            if (currentWeekStartDate) {
                // Pega a data da semana atual e adiciona 7 dias
                const nextWeekDate = new Date(currentWeekStartDate.valueOf());
                nextWeekDate.setUTCDate(currentWeekStartDate.getUTCDate() + 7);
                loadScheduleData(nextWeekDate.toISOString().split("T")[0]);
            }
        });
    }
    
    if (generatePdfButton) {
        generatePdfButton.addEventListener("click", generatePdf);
    }

    // --- Initialization ---
    console.log("Inicializando aplicação...");
    fetchBookingWindowStatus().then(() => {
        // O primeiro carregamento não passa data, usando a lógica padrão
        loadScheduleData(); 
    });
});
