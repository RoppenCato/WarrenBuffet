-- ForeverAH core: namespace, SavedVariables, event dispatch, slash command.
-- Rule (docs/03-addon.md#rules): this addon reads and displays only.
-- It never posts, buys, bids or cancels.

local ADDON, ns = ...

ns.missingEvents = {}

local handlers = {}
local frame = CreateFrame("Frame")

function ns.Print(fmt, ...)
  print("|cff33ccffForeverAH|r " .. (select("#", ...) > 0 and fmt:format(...) or fmt))
end

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
  ns.db = db
end)

ns.On("PLAYER_LOGIN", function()
  local version, build, _, interface = GetBuildInfo()
  ns.db.build = version .. " " .. build .. " " .. interface
  ns.char = UnitName("player") .. "-" .. (GetNormalizedRealmName() or GetRealmName())
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
  ns.Print("/fah scan = scan now (AH open), /fah item <id> = item in latest scan")
end

SLASH_FOREVERAH1 = "/fah"
SlashCmdList.FOREVERAH = function(msg)
  local cmd, arg = msg:lower():match("^(%S*)%s*(.-)%s*$")
  if cmd == "scan" then
    ns.Scan(true)
  elseif cmd == "item" and tonumber(arg) then
    ns.PrintItem(tonumber(arg))
  else
    Status()
  end
end
