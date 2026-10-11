-- Minimal fake of the WoW API surface ForeverAH touches. Driven by tests/test_addon.py.
-- Not a model of the real client: it encodes what the docs/wiki say, so passing here proves
-- the addon's logic, not that Forever behaves this way. That is what T3-T6 are for.

local now, clock = 1760180000, 0   -- server time (s), frame clock (ms)
local timers, handler, registered = {}, nil, {}
local replicated, lastReplicate = {}, -1e9

UNKNOWN_EVENTS = {}   -- events RegisterEvent should reject
PRINTED = {}
AUCTIONS = {}         -- { {itemID, count, buyout, minBid, bid, hasAllInfo, timeLeft}, ... }
REPLICATE_CALLS = 0
INBOX = {}            -- { {subject=, money=, expires=, invoice=, name=, bid=, ...}, ... }
MONEY = 123456
NS = {}

function print(...)
  local t = {}
  for i = 1, select("#", ...) do t[#t + 1] = tostring((select(i, ...))) end
  PRINTED[#PRINTED + 1] = table.concat(t, " ")
end

function GetServerTime() return now end
function debugprofilestop() return clock end
function Advance(sec) now = now + sec clock = clock + sec * 1000 end

C_Timer = {
  After = function(delay, fn) timers[#timers + 1] = { at = clock + delay * 1000, fn = fn } end,
}

-- One rendered frame: 16 ms pass, due timers run. Timers created now run next frame at the earliest.
function Frame()
  clock = clock + 16
  local due = timers
  timers = {}
  for _, t in ipairs(due) do
    if t.at <= clock then t.fn() else timers[#timers + 1] = t end
  end
end

function CreateFrame()
  local f = {}
  function f:RegisterEvent(event)
    if UNKNOWN_EVENTS[event] then error("Attempt to register unknown event " .. event) end
    registered[event] = true
  end
  function f:SetScript(_, fn) handler = fn end
  return f
end

function Fire(event, ...)
  if registered[event] then handler(nil, event, ...) end
end

function hooksecurefunc(tbl, name, hook)
  local orig = tbl[name]
  tbl[name] = function(...)
    local r = orig(...)
    hook(...)
    return r
  end
end

C_AuctionHouse = {}

function C_AuctionHouse.ReplicateItems()
  REPLICATE_CALLS = REPLICATE_CALLS + 1
  if now - lastReplicate >= 900 then
    replicated, lastReplicate = AUCTIONS, now
  else
    replicated = {}   -- throttled: empty market, no error
  end
end

function C_AuctionHouse.GetNumReplicateItems() return #replicated end

function C_AuctionHouse.GetReplicateItemInfo(i)
  local a = replicated[i + 1]
  return "", nil, a[2], -1, false, 0, nil, a[4], 0, a[3], a[5], nil, nil, nil, nil, 0, a[1], a[6]
end

function C_AuctionHouse.GetReplicateItemTimeLeft(i) return replicated[i + 1][7] end
-- Changed 2026-10-11 (beta T3): the real function takes an ItemLocation and raises on an item
-- id. The stub accepted anything, which hid the error the first beta run hit.
-- function C_AuctionHouse.GetItemCommodityStatus() return 2 end
function C_AuctionHouse.GetItemCommodityStatus(item)
  if type(item) ~= "table" then error("bad argument #1 to 'GetItemCommodityStatus'") end
  return 2
end
function C_AuctionHouse.PostItem() return false end
function C_AuctionHouse.PostCommodity() return false end
function C_AuctionHouse.PlaceBid() end
function C_AuctionHouse.CalculateItemDeposit(_, duration) return 100 * duration end
function C_AuctionHouse.CalculateCommodityDeposit(_, _, quantity) return 7 * quantity end

C_Item = {
  DoesItemExist = function(item) return item.id ~= nil end,
  GetItemID = function(item) return item.id end,
  GetItemNameByID = function(id) return ({ [2589] = "Linen Cloth", [2770] = "Copper Ore" })[id] end,
}

AUCTION_EXPIRED_MAIL_SUBJECT = "Auction expired: %s"
AUCTION_REMOVED_MAIL_SUBJECT = "Auction cancelled: %s"
AUCTION_OUTBID_MAIL_SUBJECT = "Outbid on %s"

function GetInboxNumItems() return #INBOX, #INBOX end

function GetInboxHeaderInfo(i)
  local m = INBOX[i]
  return nil, nil, "Horde Auction House", m.subject, m.money or 0, 0, (m.expires - now) / 86400, m.item and 1 or nil
end

function GetInboxInvoiceInfo(i)
  local m = INBOX[i]
  if not m.invoice then return end
  return m.invoice, m.name, "Someone", m.bid, m.buyout, m.deposit, m.fee, 0, 0, 0, m.count, false
end

function GetInboxItem(i)
  local m = INBOX[i]
  if m.item then return m.name, m.item, 0, m.itemCount or 1, 1, true end
end

function UnitName() return "Tester" end
function GetRealmName() return "Beta Realm" end
function GetNormalizedRealmName() return "BetaRealm" end
function UnitFactionGroup() return "Horde" end
function GetCurrentRegion() return 1 end
function GetRealZoneText() return "Orgrimmar" end
function GetBuildInfo() return "12.1.5", "99999", "Oct 1 2026", 120105 end
function GetMoney() return MONEY end
SlashCmdList = {}

function LoadAddonFile(name, src)
  assert(loadstring(src, "@" .. name))("ForeverAH", NS)
end

-- ForeverAHDB as text, in the layout the client writes SavedVariables.
function Dump()
  local out = {}
  local function w(v, indent)
    if type(v) == "table" then
      local n, inner = #v, indent .. "\t"
      out[#out + 1] = "{\n"
      for i = 1, n do
        out[#out + 1] = inner
        w(v[i], inner)
        out[#out + 1] = ", -- [" .. i .. "]\n"
      end
      local keys = {}
      for k in pairs(v) do
        if not (type(k) == "number" and k >= 1 and k <= n and k % 1 == 0) then keys[#keys + 1] = k end
      end
      table.sort(keys, function(a, b) return tostring(a) < tostring(b) end)
      for _, k in ipairs(keys) do
        out[#out + 1] = inner .. "[" .. (type(k) == "number" and tostring(k) or string.format("%q", k)) .. "] = "
        w(v[k], inner)
        out[#out + 1] = ",\n"
      end
      out[#out + 1] = indent .. "}"
    elseif type(v) == "string" then
      out[#out + 1] = string.format("%q", v)
    else
      out[#out + 1] = tostring(v)
    end
  end
  out[#out + 1] = "\nForeverAHDB = "
  w(ForeverAHDB, "")
  out[#out + 1] = "\n"
  return table.concat(out)
end
