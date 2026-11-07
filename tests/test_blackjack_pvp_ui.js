const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const source = fs.readFileSync("app.js", "utf8");
const context = vm.createContext({CURRENT_UID: 42, fmtNum: String});
vm.runInContext(source.slice(source.indexOf("function blackjackPvpDrawText("), source.indexOf("function blackjackPvpHistoryRowHTML(")), context);
const draw = {creatorId: 42, opponentId: 99, creatorRefund: 20, opponentRefund: 10, betAmount: 10, isDraw: true};
assert.equal(context.blackjackPvpDrawText(draw), "Ничья · Возврат: 20⭐️");
assert.equal(context.blackjackPvpHistoryOutcomeHTML(draw), "Ничья · Возврат: 20⭐️");
context.CURRENT_UID = 99;
assert.equal(context.blackjackPvpDrawText(draw), "Ничья · Возврат: 10⭐️");
context.CURRENT_UID = 11;
assert.equal(context.blackjackPvpDrawText(draw), "Ничья · Возвраты: 20 / 10⭐️");
assert.equal(context.blackjackPvpDrawText({betAmount: 5}), "Ничья · Возвраты: 5 / 5⭐️");
assert.equal(context.blackjackPvpDrawText({...draw, creatorRefund: 0, opponentRefund: 0}), "Ничья · Возвраты: 0 / 0⭐️");
assert.ok(source.includes("data.isDraw ? blackjackPvpDrawText(data)"));
assert.ok(source.includes("blackjackPvpDrawText(state)"));
console.log("Blackjack PvP individual refunds: passed");
