-- Inventory: what the character holds and has listed (docs/03-addon.md#inventory).
-- Needed for "what to sell" and "what to repost". Read-only: it looks at bags, the bank while
-- it is open, and the list of own auctions. It moves, posts and cancels nothing.
--
-- Latest state only - the ledger has the history. Soulbound items are left out (not sellable).
--   ForeverAHDB.inv[char] = {
--     bags = "itemID:count,...",      bagsTs = server time      carried bags
--     bank = "itemID:count,...",      bankTs                    character bank (seen while open)
--     abank = "itemID:count,...",     abankTs                   account bank, if the client has one
--     auctions = "auctionID:itemID:qty:buyout:bid:status:secondsLeft;...", auctionsTs
--                                     status 0 = active, 1 = sold; buyout as the client reports it
--     err = "which: message"          first snapshot error this session, for diagnosis
--   }

local _, ns = ...

local C_AuctionHouse = C_AuctionHouse or {}

-- Bag indexes are picked by Enum.BagIndex name, because the numbers differ between clients
-- (5 is a reagent bag in Mainline and the first bank bag in Classic).
local CARRIED = { "^Backpack$", "^Bag_%d+$", "^ReagentBag$" }
local BANK = { "^Bank$", "^BankBag_%d+$", "^CharacterBankTab_%d+$", "^Reagentbank$" }
local ACCOUNT = { "^AccountBankTab_%d+$" }

local function Indexes(patterns, fallback)
  if not (Enum and Enum.BagIndex) then return fallback end
  local out = {}
  for name, index in pairs(Enum.BagIndex) do
    for _, pat in ipairs(patterns) do
      if name:match(pat) then
        out[#out + 1] = index
        break
      end
    end
  end
  return out
end

local carried = Indexes(CARRIED, { 0, 1, 2, 3, 4 })
ns.CarriedBags = carried   -- added 2026-10-11 (v0.9): Disenchant.lua compares the same bags
local bank = Indexes(BANK, { -1, 5, 6, 7, 8, 9, 10, 11 })
local account = Indexes(ACCOUNT, {})

-- "itemID:count,..." over the given bags, or nil when none of them can be read right now
-- (bank closed, logging out) so that a good snapshot is never replaced by an empty one.
local function Count(indexes)
  local counts, ids, slots = {}, {}, 0
  for _, bag in ipairs(indexes) do
    local n = C_Container.GetContainerNumSlots(bag) or 0
    slots = slots + n
    for slot = 1, n do
      local info = C_Container.GetContainerItemInfo(bag, slot)
      if info and info.itemID and not info.isBound then
        if not counts[info.itemID] then ids[#ids + 1] = info.itemID end
        counts[info.itemID] = (counts[info.itemID] or 0) + (info.stackCount or 1)
      end
    end
  end
  if slots == 0 then return nil end
  table.sort(ids)
  for k, id in ipairs(ids) do ids[k] = id .. ":" .. counts[id] end
  return table.concat(ids, ",")
end

local function Auctions()
  local out = {}
  for i = 1, C_AuctionHouse.GetNumOwnedAuctions() do
    local a = C_AuctionHouse.GetOwnedAuctionInfo(i)
    if a then
      out[#out + 1] = table.concat({
        a.auctionID or 0, a.itemKey and a.itemKey.itemID or 0, a.quantity or 0, a.buyoutAmount or 0,
        a.bidAmount or 0, a.status or 0, math.floor(a.timeLeftSeconds or 0),
      }, ":")
    end
  end
  return table.concat(out, ";")
end

-- pcall: this API is unverified in Forever. A failure is kept in the file instead of
-- interrupting play, and never overwrites the last good snapshot.
local function Save(key, fn, ...)
  if not ns.char then return end
  local inv = ns.db.inv[ns.char]
  if not inv then
    inv = {}
    ns.db.inv[ns.char] = inv
  end
  local ok, result = pcall(fn, ...)
  if not ok then
    inv.err = inv.err or (key .. ": " .. tostring(result))
  elseif result then
    inv[key], inv[key .. "Ts"] = result, GetServerTime()
  end
end

local bankOpen, queued = false, false

local function Snapshot()
  queued = false
  Save("bags", Count, carried)
  if bankOpen then
    Save("bank", Count, bank)
    if #account > 0 then Save("abank", Count, account) end
  end
end

-- Bag events come in bursts while looting; one snapshot a second later is enough.
local function Queue()
  if queued then return end
  queued = true
  C_Timer.After(1, Snapshot)
end

ns.On("PLAYER_LOGIN", function()
  if ns.db.inv[ns.char] then ns.db.inv[ns.char].err = nil end
end)
ns.On("PLAYER_ENTERING_WORLD", Queue)
ns.On("BAG_UPDATE_DELAYED", Queue)
ns.On("PLAYERBANKSLOTS_CHANGED", Queue)
ns.On("BANKFRAME_OPENED", function()
  bankOpen = true
  Queue()
end)
ns.On("BANKFRAME_CLOSED", function()
  if bankOpen then Snapshot() end   -- last look, if the bank can still be read
  bankOpen = false
end)

local ahOpen = false
ns.On("AUCTION_HOUSE_SHOW", function()
  ahOpen = true
  -- Ask for our own auctions: a read-only query, the same one the Auctions tab sends.
  C_Timer.After(2, function()
    if ahOpen and C_AuctionHouse.QueryOwnedAuctions then
      Save("auctionsQuery", C_AuctionHouse.QueryOwnedAuctions, {})
    end
  end)
end)
ns.On("AUCTION_HOUSE_CLOSED", function() ahOpen = false end)
ns.On("OWNED_AUCTIONS_UPDATED", function() Save("auctions", Auctions) end)

local function Entries(text, sep)
  return text and text ~= "" and select(2, text:gsub("[^" .. sep .. "]+", "")) or 0
end

function ns.InventoryStatus()
  local inv = ns.db.inv[ns.char or ""]
  if not inv then return ns.Print("inventory: nothing saved yet") end
  ns.Print("inventory: %d items in bags, %d in bank%s, %d own auctions%s",
    Entries(inv.bags, ","), Entries(inv.bank, ","), inv.bankTs and "" or " (open the bank once)",
    Entries(inv.auctions, ";"), inv.auctionsTs and "" or " (open the AH once)")
  if inv.err then ns.Print("inventory error: %s", inv.err) end
end
