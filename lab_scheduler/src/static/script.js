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
    function showMessage(element, message, type = '') { /* ... (código sem alteração) ... */ }
    function showBookingStatus(message, type = 'info') { /* ... (código sem alteração) ... */ }
    function getMonday(d) { /* ... (código sem alteração) ... */ }
    function toYYYYMMDD(date) { /* ... (código sem alteração) ... */ }

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
    async function initializeApp() { /* ... (código sem alteração) ... */ }
    async function loadScheduleFor(startDateStr) { /* ... (código sem alteração) ... */ }

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
        periods.forEach(() => subHeaderRow.innerHTML += "<th>Manhã</th><th>Tarde</th>");
        thead.appendChild(subHeaderRow);
        table.appendChild(thead);

        rooms.forEach(room => {
            const row = document.createElement("tr");
            const roomCell = document.createElement("td");
            roomCell.textContent = room.name;
            roomCell.className = "room-name";
            row.appendChild(row);

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

    // ... (Resto das funções: checkIfBookingAllowed, handleSlotClick, etc. sem alteração)

    // --- Event Listeners ---
    if (adminLoginLink) {
        adminLoginLink.addEventListener("click", (e) => {
            e.preventDefault();
            enterAdminMode();
        });
    }
    // ... (Resto dos event listeners sem alteração)

    // --- Inicialização ---
    initializeApp();
});
