const board = document.querySelectorAll(".cell");
const statusDisplay = document.querySelector(".status");
const resetButton = document.querySelector(".reset-btn");

let currentPlayer = "X";
let gameActive = true;
let gameState = ["", "", "", "", "", "", "", "", ""]; 

const winningConditions = [
 [0, 1, 2], [3, 4, 5], [6, 7, 8],
 [0, 3, 6], [1, 4, 7], [2, 5, 8],
 [0, 4, 8], [2, 4, 6]
];

function handleCellClick(e) {
 const clickedCell = e.target.closest(".cell");
 const clickedCellIndex = parseInt(clickedCell.getAttribute("data-index"));
 
 if (gameState[clickedCellIndex] !== "" || !gameActive) {
 return;
 }
 
 gameState[clickedCellIndex] = currentPlayer;
 clickedCell.textContent = currentPlayer;
 clickedCell.classList.add(currentPlayer === "X" ? "x-cell" : "o-cell");
 
 checkWin();
}

function checkWin() {
 let roundWon = false;
 
 for (let i = 0; i < winningConditions.length; i++) {
 const [a, b, c] = winningConditions[i];
 if (gameState[a] === "" || gameState[b] === "" || gameState[c] === "") {
 continue;
 }
 if (gameState[a] === gameState[b] && gameState[b] === gameState[c]) {
 roundWon = true;
 break;
 }
 }
 
 if (roundWon) {
 statusDisplay.textContent = `Giocatore ${currentPlayer} ha vinto!`;
 gameActive = false;
 highlightWinningCells();
 return;
 }
 
 if (!gameState.includes("")) {
 statusDisplay.textContent = "Pareggio!";
 gameActive = false;
 return;
 }
 
 currentPlayer = currentPlayer === "X" ? "O" : "X";
 statusDisplay.textContent = `Turno di: ${currentPlayer}`;
}

function highlightWinningCells() {
 const winningCondition = winningConditions.find(condition => {
 return gameState[condition[0]] !== "" && 
 gameState[condition[1]] !== "" && 
 gameState[condition[2]] !== "" &&
 gameState[condition[0]] === gameState[condition[1]] && 
 gameState[condition[1]] === gameState[condition[2]];
 });
 
 if (winningCondition) {
 const [a, b, c] = winningCondition;
 board[a].classList.add("winning-cell");
 board[b].classList.add("winning-cell");'