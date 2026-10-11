-- ForeverAH core: namespace, SavedVariables, event dispatch, slash command.
-- Rule (docs/03-addon.md#rules): this addon reads and displays only.
-- It never posts, buys, bids or cancels.

local ADDON, ns = ...

ns.missingEvents = {}

local handlers = {}
local frame = CreateFrame("Frame")

-- Changed 2026-10-11: messages go to the addon's own window (UI.lua) instead of the chat frame,
-- which got noisy. Chat is only the fallback when the window could not be built.
-- function ns.Print(fmt, ...)
--   print("|cff33ccffForeverAH|r " .. (select("#", ...) > 0 and fmt:format(...) or fmt))
-- end
local function Emit(quiet, fmt, ...)
  local msg = select("#", ...) > 0 and fmt:format(...) or fmt
  if not (ns.Log and ns.Log(msg, quiet)) then print("|cff33ccffForeverAH|r " .. msg) end
end

function ns.Print(fmt, ...) Emit(false, fmt, ...) end   -- may open the window
function ns.Note(fmt, ...) Emit(true, fmt, ...) end     -- never opens it; the button counts it

-- pcall: RegisterEvent raises on events the client doesn't know. We want a list of
-- those (T6), not a broken addon.
function ns.On(event, fn)
  local list = handlers[event]
  if not list then
    list = {}
    handlers[event] = list
    if not pcall(frame.RegisterEvent, frame, event) then
      table.insert(ns.missingEvents, event)
    end
  end
  list[#list + 1] = fn
end

frame:SetScript("OnEvent", function(_, event, ...)
  local list = handlers[event]
  for i = 1, #list do list[i](...) end
end)

ns.On("ADDON_LOADED", function(name)
  if name ~= ADDON then return end
  ForeverAHDB = ForeverAHDB or {}
  local db = ForeverAHDB
  db.v = db.v or 1
  db.scans = db.scans or {}        -- oldest first, see Scanner.lua
  db.ledger = db.ledger or {}      -- see Ledger.lua
  db.mailSeen = db.mailSeen or {}  -- mail dedup, see Ledger.lua
  db.inv = db.inv or {}            -- added 2026-10-11: holdings per character, see Inventory.lua
  db.ui = db.ui or {}              -- added 2026-10-11: window and button state, see UI.lua
  ns.db = db
end)

ns.On("PLAYER_LOGIN", function()
  local version, build, _, interface = GetBuildInfo()
  ns.db.build = version .. " " .. build .. " " .. interface
  ns.char = UnitName("player") .. "-" .. (GetNormalizedRealmName() or GetRealmName())
  -- Added 2026-10-11: save the events this client rejected, so the T6 answer is in the
  -- SavedVariables file and doesn't have to be copied from chat.
  ns.db.missing = table.concat(ns.missingEvents, ",")
end)

local function Status()
  local db = ns.db
  local raw = 0
  for _, rec in ipairs(db.scans) do
    if rec.raw then raw = raw + 1 end
  end
  ns.Print("client %s", db.build or "?")
  if db.lastScan then
    ns.Print("last scan %d min ago", math.floor((GetServerTime() - db.lastScan) / 60))
  end
  ns.Print("%d scans stored (%d with raw rows), %d ledger rows, %d throttled replies",
    #db.scans, raw, #db.ledger, db.throttled or 0)
  if #ns.missingEvents > 0 then
    ns.Print("events missing in this client: %s", table.concat(ns.missingEvents, ", "))
  end
  ns.InventoryStatus()   -- added 2026-10-11 with Inventory.lua
  -- Changed 2026-10-11: trader line and command added (several characters, one of them trades).
  -- ns.Print("/fah scan = scan now (AH open), /fah item <id> = item in latest scan")
  ns.Print("trader: %s", db.trader or "not set - type /fah trader on the character that sells")
  ns.Print("/fah scan = scan now (AH open), /fah item <id> = item in latest scan, /fah trader = this character trades")
end

SLASH_FOREVERAH1 = "/fah"
SlashCmdList.FOREVERAH = function(msg)
  local cmd, arg = msg:lower():match("^(%S*)%s*(.-)%s*$")
  if cmd == "scan" then
    ns.Scan(true)
  elseif cmd == "item" and tonumber(arg) then
    ns.PrintItem(tonumber(arg))
  -- Added 2026-10-11: mark this character as the one that buys and sells. Scans, the ledger and
  -- the inventory work on every character; the dashboard needs to know whose gold to plan with.
  elseif cmd == "trader" then
    ns.db.trader = ns.char
    ns.Print("trader set to %s", ns.char)
  else
    Status()
  end
end
