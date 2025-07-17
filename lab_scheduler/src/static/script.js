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
        const now = new Date();
        const currentDayOfWeek = now.getDay();
        const currentHour = now.getHours();
        if ( (currentDayOfWeek === 4 && currentHour >= 18) || currentDayOfWeek >= 5 || currentDayOfWeek === 0 ) {
            const nextWeek = new Date(now);
            const daysUntilMonday = (1 - currentDayOfWeek + 7) % 7;
            if (daysUntilMonday === 0) {
                nextWeek.setDate(now.getDate() + 7);
            } else {
                nextWeek.setDate(now.getDate() + daysUntilMonday);
            }
            return nextWeek.toISOString().split("T")[0];
        }
        return null;
    }

    // --- Funções de Status e Salas (sem alteração) ---
    async function fetchBookingWindowStatus() {
        try {
            const response = await fetch(`${API_BASE_URL}/booking-window-status`);
            if (!response.ok) {
                throw new Error("Servidor não respondeu ao status.");
            }
            bookingWindowStatus = await response.json();
            console.log("Status da janela de agendamento carregado:", bookingWindowStatus);
            updateBookingStatusDisplay();
            return true; // Retorna sucesso
        } catch (error) {
            console.error("Falha crítica ao buscar status do agendamento:", error);
            showBookingStatusMessage("Não foi possível verificar o status do agendamento.", "error");
            showScheduleMessage("Não é possível carregar a escala sem o status do servidor.", "error");
            return false; // Retorna falha
        }
    }
    function updateBookingStatusDisplay() { /* ...código sem alteração... */ }
    async function fetchAllRooms() { /* ...código sem alteração... */ }

    // --- Lógica de Carregamento da Escala (sem alteração) ---
    async function loadScheduleData(inputDateStr = null) {
        // Adicionada uma verificação para garantir que o status foi carregado
        if (!bookingWindowStatus) {
            showScheduleMessage("Aguardando status do servidor para carregar a escala.", "error");
            console.error("Tentativa de carregar a escala sem bookingWindowStatus definido.");
            return;
        }
        
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
            showScheduleMessage(`Erro ao carregar escala: ${error.message}`, "error");
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
    if (loadScheduleButton) { /* ...código sem alteração... */ }
    if (prevWeekButton) { /* ...código sem alteração... */ }
    if (nextWeekButton) { /* ...código sem alteração... */ }
    if (generatePdfButton) { /* ...código sem alteração... */ }

    // --- Initialization (CORRIGIDA) ---
    async function initializeApp() {
        console.log("Inicializando aplicação...");
        // Primeiro, espera o status ser carregado.
        const statusLoaded = await fetchBookingWindowStatus();
        
        // A escala só é carregada SE o status foi obtido com sucesso.
        if (statusLoaded) {
            loadScheduleData();
        } else {
            console.error("Inicialização interrompida: não foi possível carregar o status da janela de agendamento.");
        }
    }

    initializeApp();
});
