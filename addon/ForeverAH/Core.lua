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

-- Added 2026-10-11 (v0.7): readable numbers and money for the window.
function ns.Number(n)   -- 96635 -> 96,635
  return BreakUpLargeNumbers and BreakUpLargeNumbers(n) or tostring(n)
end

function ns.Money(copper)   -- coin icons where the client can draw them, else "1g 2s 3c"
  copper = math.floor(math.abs(copper or 0) + 0.5)
  local coins = C_CurrencyInfo and C_CurrencyInfo.GetCoinTextureString or GetCoinTextureString
  if coins then return coins(copper) end
  local g, s, c = math.floor(copper / 10000), math.floor(copper / 100) % 100, copper % 100
  return (g > 0 and g .. "g " or "") .. ((g > 0 or s > 0) and s .. "s " or "") .. c .. "c"
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

-- Added 2026-10-11: errors are kept in the SavedVariables file (ForeverAHDB.errors, last 20) so
-- they can be read from the file afterwards. They still reach the game's own error display.
local earlyErrors = {}
function ns.Error(where, err)
  local text = GetServerTime() .. " " .. where .. ": " .. tostring(err)
  local list = ns.db and ns.db.errors or earlyErrors
  list[#list + 1] = text
  while #list > 20 do table.remove(list, 1) end
  if geterrorhandler then geterrorhandler()(text) end
end

-- Changed 2026-10-11: one failing handler no longer stops the others. On the beta a new
-- character's first login failed in Core's PLAYER_LOGIN, which silently skipped the ledger's
-- login handler and left a row with character "?".
-- frame:SetScript("OnEvent", function(_, event, ...)
--   local list = handlers[event]
--   for i = 1, #list do list[i](...) end
-- end)
frame:SetScript("OnEvent", function(_, event, ...)
  local list = handlers[event]
  for i = 1, #list do
    local ok, err = pcall(list[i], ...)
    if not ok then ns.Error(event, err) end
  end
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
  db.errors = db.errors or {}      -- added 2026-10-11: see ns.Error
  db.recipes = db.recipes or {}          -- added 2026-10-11 (v0.9): see Recipes.lua
  db.disenchants = db.disenchants or {}  -- added 2026-10-11 (v0.9): see Disenchant.lua
  for _, text in ipairs(earlyErrors) do db.errors[#db.errors + 1] = text end
  ns.db = db
end)

function ns.ResolveChar()
  local name, realm = UnitName("player"), GetNormalizedRealmName() or GetRealmName()
  if name and name ~= "" and realm and realm ~= "" then ns.char = name .. "-" .. realm end
  return ns.char
end

ns.On("PLAYER_ENTERING_WORLD", function()
  if not ns.char then ns.ResolveChar() end
end)

ns.On("PLAYER_LOGIN", function()
  local version, build, _, interface = GetBuildInfo()
  ns.db.build = version .. " " .. build .. " " .. interface
  -- Changed 2026-10-11: the name can be missing this early (seen on a new character's first
  -- login), so resolve it without raising and try again when the world loads.
  -- ns.char = UnitName("player") .. "-" .. (GetNormalizedRealmName() or GetRealmName())
  ns.ResolveChar()
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
  -- ns.Print("/fah scan = scan now (AH open), /fah item <id> = item in latest scan, /fah trader = this character trades")
  ns.Print("/fah scan  /fah item <id>  /fah trader  /fah debug")   -- 2026-10-11: shortened, debug added
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
  -- Added 2026-10-11 (v0.7): the scan diagnostics used for the beta tests, off by default.
  elseif cmd == "debug" then
    ns.db.debug = not ns.db.debug
    ns.Print("scan diagnostics %s", ns.db.debug and "on" or "off")
  else
    Status()
  end
end
