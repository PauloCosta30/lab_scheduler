document.addEventListener("DOMContentLoaded", () => {
    // --- Elementos DOM (sem alteração) ---
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

    // --- Variáveis Globais (sem alteração) ---
    const API_BASE_URL = "/api";
    let allRooms = [];
    let selectedSlots = [];
    let currentFetchedBookings = [];
    let currentWeekStartDate;
    let bookingWindowStatus = null;

    // --- Funções Helper (sem alteração) ---
    function getTodayUTC() { /* ...código sem alteração... */ }
    function parseDateStrToUTC(dateStr) { /* ...código sem alteração... */ }
    function showModalMessage(message, type) { /* ...código sem alteração... */ }
    function showScheduleMessage(message, type) { /* ...código sem alteração... */ }
    function showBookingStatusMessage(message, type) { /* ...código sem alteração... */ }

    // --- Lógica de Exibição da Semana (CORRIGIDA) ---
    function getWeekToDisplay() {
        const now = new Date();
        const currentDayOfWeek = now.getDay(); // 0=Domingo, 1=Segunda, ..., 6=Sábado
        const currentHour = now.getHours();
        
        console.log(`=== DETERMINANDO SEMANA PARA EXIBIR (v2) ===`);
        console.log(`Dia/Hora local: ${currentDayOfWeek} / ${currentHour}`);

        if ( (currentDayOfWeek === 4 && currentHour >= 18) || currentDayOfWeek >= 5 || currentDayOfWeek === 0 ) {
            console.log(`DECISÃO: EXIBIR PRÓXIMA SEMANA`);
            
            const nextWeek = new Date(now);
            
            // --- LÓGICA DE CÁLCULO CORRIGIDA E SIMPLIFICADA ---
            // 1. Encontra a diferença de dias até a próxima segunda-feira.
            // (1 - currentDayOfWeek) nos dá a diferença para a segunda-feira desta semana.
            // Adicionamos 7 para garantir que seja a da próxima semana.
            // O operador % 7 lida com o caso do domingo (day=0).
            const daysUntilMonday = (1 - currentDayOfWeek + 7) % 7;
            
            // Se hoje for segunda, daysUntilMonday será 0, então pulamos 7 dias.
            if (daysUntilMonday === 0) {
                nextWeek.setDate(now.getDate() + 7);
            } else {
                nextWeek.setDate(now.getDate() + daysUntilMonday);
            }
            
            return nextWeek.toISOString().split("T")[0];
        }
        
        console.log(`DECISÃO: EXIBIR SEMANA ATUAL`);
        return null;
    }

    // --- Funções de Status e Salas (sem alteração) ---
    async function fetchBookingWindowStatus() { /* ...código sem alteração... */ }
    function updateBookingStatusDisplay() { /* ...código sem alteração... */ }
    async function fetchAllRooms() { /* ...código sem alteração... */ }

    // --- Lógica de Carregamento da Escala (sem alteração) ---
    async function loadScheduleData(inputDateStr = null) {
        console.log(`Iniciando carregamento da escala. Data de entrada: ${inputDateStr}`);
        
        try {
            let referenceDate;
            
            if (inputDateStr) {
                referenceDate = parseDateStrToUTC(inputDateStr);
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

    // --- Event Listeners (sem alteração) ---
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

    if (prevWeekButton) {
        prevWeekButton.addEventListener("click", () => {
            if (currentWeekStartDate) {
                const prevWeekDate = new Date(currentWeekStartDate.valueOf());
                prevWeekDate.setUTCDate(currentWeekStartDate.getUTCDate() - 7);
                loadScheduleData(prevWeekDate.toISOString().split("T")[0]);
            }
        });
    }

    if (nextWeekButton) {
        nextWeekButton.addEventListener("click", () => {
            if (currentWeekStartDate) {
                const nextWeekDate = new Date(currentWeekStartDate.valueOf());
                nextWeekDate.setUTCDate(currentWeekStartDate.getUTCDate() + 7);
                loadScheduleData(nextWeekDate.toISOString().split("T")[0]);
            }
        });
    }
    
    if (generatePdfButton) {
        generatePdfButton.addEventListener("click", generatePdf);
    }

    // --- Initialization (sem alteração) ---
    console.log("Inicializando aplicação...");
    fetchBookingWindowStatus().then(() => {
        loadScheduleData(); 
    });
});
