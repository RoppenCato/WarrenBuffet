-- Ledger: own posts, purchases, sales, expiries (docs/03-addon.md#ledger).
-- Observes the player's own clicks (hooksecurefunc runs after the original call) and reads
-- mail. It never calls an AH action itself.
--
-- Row (ForeverAHDB.ledger[i]): "ts,char,event,key=value,...[,name=Item Name]"
-- name is always last because item names may contain commas.
--   AH events: post, cancel, bid, buy_commodity, buy_done, buy_item
--   mail:      sold, sold_pending, bought, expired, cancelled, outbid
--   other:     gold (login/logout)
-- Money is copper. dur: 1 = 12 h, 2 = 24 h, 3 = 48 h.

local _, ns = ...

-- Added 2026-10-11: if this client has no Mainline AH namespace, skip the AH hooks instead of
-- erroring at load. Mail and gold rows still work; Scanner.lua reports the missing API.
local C_AuctionHouse = C_AuctionHouse or {}

local MAIL_TOL = 2   -- s; a mail is the same mail if its expiry time matches within this

local function KV(...)
  local t = {}
  for i = 1, select("#", ...), 2 do
    local k, v = select(i, ...)
    if v ~= nil then t[#t + 1] = k .. "=" .. tostring(v) end
  end
  return table.concat(t, ",")
end

local function Log(event, fields, name)
  local row = GetServerTime() .. "," .. (ns.char or "?") .. "," .. event
  if fields and fields ~= "" then row = row .. "," .. fields end
  if name then row = row .. ",name=" .. name end
  ns.db.ledger[#ns.db.ledger + 1] = row
  if event ~= "gold" then ns.Print("ledger: %s", row) end
end

local function Try(fn, ...)
  if not fn then return nil end
  local ok, v = pcall(fn, ...)
  return ok and v or nil
end

---------------------------------------------------------------------------------------------
-- Posting: remember what the player just posted, write the row when the AH confirms it.

local pending       -- fields of the last PostItem/PostCommodity call
local created = 0   -- auctions confirmed for that call (one call can create several)

local function OnPost(kind, item, duration, quantity, bid, buyout, unit)
  local itemID, deposit
  if item and Try(C_Item.DoesItemExist, item) then
    itemID = Try(C_Item.GetItemID, item)
    if kind == "item" then
      deposit = Try(C_AuctionHouse.CalculateItemDeposit, item, duration, quantity)
    else
      deposit = Try(C_AuctionHouse.CalculateCommodityDeposit, itemID, duration, quantity)
    end
  end
  pending = KV("kind", kind, "item", itemID, "qty", quantity, "bid", bid, "buyout", buyout,
    "unit", unit, "dur", duration, "dep", deposit)
  created = 0
end

if C_AuctionHouse.PostItem then
  hooksecurefunc(C_AuctionHouse, "PostItem", function(item, duration, quantity, bid, buyout)
    OnPost("item", item, duration, quantity, bid, buyout, nil)
  end)
end
if C_AuctionHouse.PostCommodity then
  hooksecurefunc(C_AuctionHouse, "PostCommodity", function(item, duration, quantity, unitPrice)
    OnPost("commodity", item, duration, quantity, nil, nil, unitPrice)
  end)
end

ns.On("AUCTION_HOUSE_AUCTION_CREATED", function(auctionID)
  created = created + 1
  local fields = KV("auction", auctionID, "seq", created)
  Log("post", pending and (fields .. "," .. pending) or fields)
end)

-- Join to the post row on auction id for item and price.
ns.On("AUCTION_CANCELED", function(auctionID)
  Log("cancel", KV("auction", auctionID))
end)

---------------------------------------------------------------------------------------------
-- Buying: real-time signals. The "bought" mail row is the authoritative record.

if C_AuctionHouse.PlaceBid then
  -- Buyouts go through PlaceBid too (bid = buyout price).
  hooksecurefunc(C_AuctionHouse, "PlaceBid", function(auctionID, amount)
    Log("bid", KV("auction", auctionID, "total", amount))
  end)
end

local unitPrice, totalPrice
ns.On("COMMODITY_PRICE_UPDATED", function(unit, total)
  unitPrice, totalPrice = unit, total
end)
ns.On("COMMODITY_PURCHASED", function(itemID, quantity)
  Log("buy_commodity", KV("item", itemID, "qty", quantity, "unit", unitPrice, "total", totalPrice))
end)
ns.On("AUCTION_HOUSE_PURCHASE_COMPLETED", function(auctionID)
  Log("buy_done", KV("auction", auctionID))
end)
ns.On("ITEM_PURCHASED", function(itemID)
  Log("buy_item", KV("item", itemID))
end)

---------------------------------------------------------------------------------------------
-- Mail: sales, purchases, expired, cancelled, outbid.
-- The inbox has no mail id, so a mail is identified by event + item name + count + bid and
-- its expiry time (server time + days left), which stays fixed while the mail exists.
-- mailSeen[key] = { expiry, ... } - one entry per mail already logged.

local INVOICE_EVENTS = { seller = "sold", buyer = "bought", seller_temp_invoice = "sold_pending" }
local SUBJECT_EVENTS = {
  AUCTION_EXPIRED_MAIL_SUBJECT = "expired",
  AUCTION_REMOVED_MAIL_SUBJECT = "cancelled",
  AUCTION_OUTBID_MAIL_SUBJECT = "outbid",
}

local subjectPatterns
local function SubjectEvent(subject)
  if not subjectPatterns then
    subjectPatterns = {}
    for global, event in pairs(SUBJECT_EVENTS) do
      local fmt = _G[global]   -- e.g. "Auction expired: %s"
      if fmt then
        local pat = fmt:gsub("%p", "%%%0"):gsub("%%%%s", "(.+)")
        subjectPatterns["^" .. pat .. "$"] = event
      end
    end
  end
  for pat, event in pairs(subjectPatterns) do
    local name = subject:match(pat)
    if name then return event, name end
  end
end

-- Index of the closest not-yet-matched expiry within MAIL_TOL, or nil.
local function Match(list, used, expiry)
  local best, bestDiff
  for k = 1, #list do
    local diff = math.abs(list[k] - expiry)
    if diff <= MAIL_TOL and not used[k] and (not bestDiff or diff < bestDiff) then
      best, bestDiff = k, diff
    end
  end
  return best
end

local function ScanInbox()
  local seen, now, used = ns.db.mailSeen, GetServerTime(), {}
  for i = 1, GetInboxNumItems() do
    local _, _, _, subject, money, _, daysLeft = GetInboxHeaderInfo(i)
    local invoiceType, itemName, _, bid, buyout, deposit, consignment, _, _, _, count = GetInboxInvoiceInfo(i)
    local event, name = INVOICE_EVENTS[invoiceType or ""], itemName
    if not event and subject then event, name = SubjectEvent(subject) end
    if event and daysLeft then
      if not count or count < 1 then count = nil end
      local key = event .. "|" .. (name or "") .. "|" .. (count or 0) .. "|" .. (bid or 0)
      local expiry = math.floor(now + daysLeft * 86400 + 0.5)
      local list, u = seen[key], used[key]
      if not list then list = {} seen[key] = list end
      if not u then u = {} used[key] = u end
      local k = Match(list, u, expiry)
      if k then
        u[k] = true
      else
        list[#list + 1] = expiry
        u[#list] = true
        local _, itemID, _, itemCount = GetInboxItem(i, 1)
        -- total = winning bid, fee = AH cut, dep = deposit refunded, money = copper attached
        Log(event, KV("item", itemID, "qty", count or itemCount, "total", bid, "buyout", buyout,
          "fee", consignment, "dep", deposit, "money", money, "exp", expiry), name)
      end
    end
  end
end

-- MAIL_INBOX_UPDATE fires in bursts; scan once after it settles.
local queued = false
ns.On("MAIL_INBOX_UPDATE", function()
  if queued then return end
  queued = true
  C_Timer.After(0.5, function()
    queued = false
    ScanInbox()
  end)
end)

---------------------------------------------------------------------------------------------

ns.On("PLAYER_LOGIN", function()
  -- forget mails that have expired
  local seen, now = ns.db.mailSeen, GetServerTime()
  for key, list in pairs(seen) do
    for k = #list, 1, -1 do
      if list[k] < now then table.remove(list, k) end
    end
    if #list == 0 then seen[key] = nil end
  end
  Log("gold", KV("copper", GetMoney(), "at", "login"))
end)

ns.On("PLAYER_LOGOUT", function()
  Log("gold", KV("copper", GetMoney(), "at", "logout"))
end)
