-- Scanner: full AH scan via C_AuctionHouse.ReplicateItems (docs/03-addon.md#scanner).
-- Read-only: requests and reads the auction list, nothing else.
--
-- Saved per scan (ForeverAHDB.scans[i]):
-- Changed 2026-10-11 (D15): raw rows got a 6th field, the time-left band (1 shortest .. 4 longest,
-- 0 unknown). Scans saved before this have 5 fields. buyout is the total for the row (unit price
-- x count) - confirmed on beta data.
-- --   header fields + raw = { "itemID,count,buyout,minBid,bid;..." }   (last KEEP_RAW scans)
--   header fields + raw = { "itemID,count,buyout,minBid,bid,timeLeft;..." }   (last KEEP_RAW scans)
--                 + agg = { "itemID,min,p10,p25,median,qty,auctions;..." }
-- Aggregate prices are buyout per unit in copper (rounded, at least 1), quantity-weighted:
-- pX = lowest unit price where cumulative units >= X % of the units that have a buyout.
-- qty and auctions count every row, bid-only rows included. No buyout at all -> prices 0.

local _, ns = ...

local THROTTLE = 15 * 60      -- s between successful ReplicateItems calls, account-wide
local CHUNK = 5000            -- auction rows per frame
local AGG_CHUNK = 500         -- items per frame and per saved string
local KEEP_RAW = 3            -- newest scans that keep raw rows (docs/04)
local KEEP_AGG = 40           -- scans kept in total; pipeline must ingest before this rolls over
local TIMEOUT = 120           -- s without a reply before giving up
local CHECK = { 2589, 2770 }  -- T5: Linen Cloth, Copper Ore

local state = "idle"          -- idle | waiting | processing
local scan                    -- work table of the scan in progress
local ahOpen = false

local function Abort(why)
  state, scan = "idle", nil
  ns.Print("scan not saved: %s", why)
end

-- min, p10, p25, median, qty, auctions of one item in a saved scan
local function FindAgg(rec, itemID)
  local pat = ";" .. itemID .. ",(%d+),(%d+),(%d+),(%d+),(%d+),(%d+);"
  for _, chunk in ipairs(rec.agg) do
    local min, p10, p25, med, qty, auctions = (";" .. chunk):match(pat)
    if min then
      return tonumber(min), tonumber(p10), tonumber(p25), tonumber(med), tonumber(qty), tonumber(auctions)
    end
  end
end

function ns.PrintItem(itemID, rec)
  rec = rec or ns.db.scans[#ns.db.scans]
  if not rec then return ns.Print("no scan stored") end
  local name = C_Item.GetItemNameByID and C_Item.GetItemNameByID(itemID) or "item"
  -- Changed 2026-10-11 (beta T3): GetItemCommodityStatus takes an ItemLocation, not an item id,
  -- and raised an error here after every scan. Removed; the ledger's post rows (kind=commodity)
  -- answer the AH-type question instead.
  -- -- Enum.ItemCommodityStatus: 0 unknown, 1 item, 2 commodity (T5: which AH type is this?)
  -- local status = C_AuctionHouse.GetItemCommodityStatus and C_AuctionHouse.GetItemCommodityStatus(itemID)
  local min, p10, p25, med, qty, auctions = FindAgg(rec, itemID)
  if not min then
    -- return ns.Print("%s %d: NOT in scan (commodity status %s)", name, itemID, tostring(status))
    return ns.Print("%s %d: NOT in scan", name, itemID)
  end
  -- %s for prices: %d overflows above 2^31 copper on Windows clients
  -- ns.Print("%s %d: %d auctions, %d units, min %s, p10 %s, p25 %s, median %s copper (commodity status %s)",
  --   name, itemID, auctions, qty, min, p10, p25, med, tostring(status))
  ns.Print("%s %d: %d auctions, %d units, min %s, p10 %s, p25 %s, median %s copper",
    name, itemID, auctions, qty, min, p10, p25, med)
end

local function Finish(s)
  local rec, db = s.rec, ns.db
  local done = debugprofilestop()
  rec.waitSec = math.floor(s.tReply - s.t0) / 1000
  rec.procSec = math.floor(done - s.tReply) / 1000
  rec.maxMs = math.floor(s.maxMs)
  local tl = {}
  for band = 0, 4 do
    if s.tl[band] then tl[#tl + 1] = band .. ":" .. s.tl[band] end
  end
  rec.tl = table.concat(tl, ",")

  local scans = db.scans
  scans[#scans + 1] = rec
  while #scans > KEEP_AGG do table.remove(scans, 1) end
  for k = 1, #scans - KEEP_RAW do scans[k].raw = nil end
  db.lastScan = rec.ts
  state, scan = "idle", nil

  -- Changed 2026-10-11 (v0.7): one readable line. The five lines below were for the beta tests
  -- (T3-T5); they now only show with /fah debug.
  -- ns.Print("scan saved: %d rows (AH reported %d), %d items, %d units",
  --   rec.rows, rec.n, rec.items, rec.units)
  -- ns.Print("wait %.1f s, process %.1f s in %d frames (slowest %d ms), hasAllInfo misses %d, skipped %d",
  --   rec.waitSec, rec.procSec, rec.frames, rec.maxMs, rec.miss, rec.skip)
  -- ns.Print("time-left bands: %s", rec.tl ~= "" and rec.tl or "not available")
  -- for _, itemID in ipairs(CHECK) do ns.PrintItem(itemID, rec) end
  -- ns.Print("/reload or log out to write SavedVariables")
  ns.Print("|cffffd100Scan saved|r  %s auctions, %s items, %d s", ns.Number(rec.rows), ns.Number(rec.items),
    math.floor(rec.waitSec + rec.procSec + 0.5))
  if db.debug then
    ns.Print("rows %d of %d reported, %d units", rec.rows, rec.n, rec.units)
    ns.Print("wait %.1f s, process %.1f s in %d frames (slowest %d ms), hasAllInfo misses %d, skipped %d",
      rec.waitSec, rec.procSec, rec.frames, rec.maxMs, rec.miss, rec.skip)
    ns.Print("time-left bands: %s", rec.tl ~= "" and rec.tl or "not available")
    for _, itemID in ipairs(CHECK) do ns.PrintItem(itemID, rec) end
  end
  -- Added 2026-10-11: names and vendor prices of the items just seen (Items.lua).
  if ns.RecordItems then ns.RecordItems(s.ids) end
end

local function Aggregate(s)
  if scan ~= s then return end
  local ids, items = s.ids, s.items
  local out, n = {}, 0
  local last = math.min(s.j + AGG_CHUNK - 1, #ids)
  for k = s.j, last do
    local id = ids[k]
    local it = items[id]
    local min, p10, p25, med = 0, 0, 0, 0
    if it.np > 0 then
      local prices, byPrice, total = it.prices, it.byPrice, it.bqty
      table.sort(prices)
      min, p10, p25 = prices[1], nil, nil
      local cum = 0
      for p = 1, it.np do
        local price = prices[p]
        cum = cum + byPrice[price]
        -- integer comparisons: no float rounding, so Python can reproduce this exactly
        if not p10 and cum * 10 >= total then p10 = price end
        if not p25 and cum * 4 >= total then p25 = price end
        if cum * 2 >= total then med = price break end
      end
    end
    n = n + 1
    out[n] = id .. "," .. min .. "," .. p10 .. "," .. p25 .. "," .. med .. "," .. it.qty .. "," .. it.auctions
  end
  s.rec.agg[#s.rec.agg + 1] = table.concat(out, ";") .. ";"
  s.j = last + 1
  s.rec.frames = s.rec.frames + 1
  if s.j <= #ids then
    C_Timer.After(0, function() Aggregate(s) end)
  else
    Finish(s)
  end
end

local function ProcessChunk(s)
  if scan ~= s then return end
  local t = debugprofilestop()
  local rec, items, ids, tlCount = s.rec, s.items, s.ids, s.tl
  local GetInfo = C_AuctionHouse.GetReplicateItemInfo
  -- Changed 2026-10-11 (D15): no longer a probe - it returns bands 1-4 in Forever.
  -- -- Probe only: docs/02 assumes no time left. If this exists and returns bands, we can do better.
  local GetTimeLeft = C_AuctionHouse.GetReplicateItemTimeLeft
  local rows, r = {}, 0
  local last = math.min(s.i + CHUNK, rec.n) - 1
  for idx = s.i, last do   -- replicate indexes are 0-based
    local _, _, count, _, _, _, _, minBid, _, buyout, bid, _, _, _, _, _, itemID, hasAllInfo = GetInfo(idx)
    if not itemID or itemID == 0 or not count or count < 1 then
      rec.skip = rec.skip + 1
    else
      -- itemID, count, minBid and buyout are valid even before the item is cached, so a miss
      -- is only counted, not waited for.
      if not hasAllInfo then rec.miss = rec.miss + 1 end
      buyout, minBid, bid = buyout or 0, minBid or 0, bid or 0
      r = r + 1
      -- Changed 2026-10-11 (D15): GetReplicateItemTimeLeft works in Forever (T3: bands 1-4), so
      -- the band is saved as a 6th field. 0 = not available.
      -- rows[r] = itemID .. "," .. count .. "," .. buyout .. "," .. minBid .. "," .. bid
      local band = GetTimeLeft and GetTimeLeft(idx) or 0
      tlCount[band] = (tlCount[band] or 0) + 1
      rows[r] = itemID .. "," .. count .. "," .. buyout .. "," .. minBid .. "," .. bid .. "," .. band

      local it = items[itemID]
      if not it then
        it = { qty = 0, auctions = 0, bqty = 0, np = 0, prices = {}, byPrice = {} }
        items[itemID] = it
        ids[#ids + 1] = itemID
      end
      it.qty = it.qty + count
      it.auctions = it.auctions + 1
      rec.units = rec.units + count
      if buyout > 0 then
        local unit = math.floor(buyout / count + 0.5)
        if unit < 1 then unit = 1 end
        local q = it.byPrice[unit]
        if q then
          it.byPrice[unit] = q + count
        else
          it.np = it.np + 1
          it.prices[it.np] = unit
          it.byPrice[unit] = count
        end
        it.bqty = it.bqty + count
      end
      -- Changed 2026-10-11 (D15): moved up, the band is part of the row now.
      -- if GetTimeLeft then
      --   local band = GetTimeLeft(idx)
      --   if band then tlCount[band] = (tlCount[band] or 0) + 1 end
      -- end
    end
  end
  if r > 0 then rec.raw[#rec.raw + 1] = table.concat(rows, ";") .. ";" end
  rec.rows = rec.rows + r
  rec.frames = rec.frames + 1
  s.i = last + 1
  s.maxMs = math.max(s.maxMs, debugprofilestop() - t)
  if s.i < rec.n then
    C_Timer.After(0, function() ProcessChunk(s) end)
  else
    rec.items = #ids
    table.sort(ids)
    s.j = 1
    C_Timer.After(0, function() Aggregate(s) end)
  end
end

-- force = true skips our own 15-min timer (the server throttle still applies).
function ns.Scan(force)
  -- Added 2026-10-11: a clear message instead of a Lua error if the Mainline scan API is absent
  -- (that would itself be the T3 result).
  if not (C_AuctionHouse and C_AuctionHouse.ReplicateItems) then
    return ns.Print("C_AuctionHouse.ReplicateItems is missing in this client - cannot scan")
  end
  if state ~= "idle" then return ns.Print("scan already %s", state) end
  if not ahOpen then return ns.Print("open the auction house first") end
  local now = GetServerTime()
  local wait = THROTTLE - (now - (ns.db.lastScan or 0))
  if wait > 0 and not force then
    -- Changed 2026-10-11: a note, so opening the AH between scans does not pop the window up.
    -- return ns.Print("next scan in %d min (/fah scan to try anyway)", math.ceil(wait / 60))
    return ns.Note("next scan in %d min (/fah scan to try anyway)", math.ceil(wait / 60))
  end
  local realm, faction = GetRealmName(), UnitFactionGroup("player") or "?"
  local s = {
    t0 = debugprofilestop(), i = 0, maxMs = 0, items = {}, ids = {}, tl = {},
    rec = {
      id = now .. ":" .. realm .. ":" .. faction,
      ts = now, realm = realm, faction = faction,
      region = GetCurrentRegion(), zone = GetRealZoneText(),   -- pipeline maps these to a house id
      n = 0, rows = 0, items = 0, units = 0, miss = 0, skip = 0, frames = 0,
      raw = {}, agg = {},
    },
  }
  state, scan = "waiting", s
  -- Changed 2026-10-11 (beta T3): a throttled request gets no reply at all in Forever (no event,
  -- not an empty list), so the timeout is the throttle signal. Say so, and warn up front.
  -- C_Timer.After(TIMEOUT, function()
  --   if scan == s and state == "waiting" then Abort("no reply in " .. TIMEOUT .. " s - throttled?") end
  -- end)
  C_Timer.After(TIMEOUT, function()
    if scan == s and state == "waiting" then
      Abort("no reply in " .. TIMEOUT .. " s - throttled (the server stays silent inside its 15 min)")
    end
  end)
  if wait > 0 then
    ns.Print("last scan was %d min ago - the server will probably ignore this request",
      math.floor((now - ns.db.lastScan) / 60))
  end
  -- ns.Print("requesting full scan - keep the AH open")   (2026-10-11: plainer wording)
  ns.Print("Scanning the auction house - keep it open")
  C_AuctionHouse.ReplicateItems()
end

ns.On("AUCTION_HOUSE_SHOW", function()
  ahOpen = true
  ns.Scan(false)
end)

ns.On("AUCTION_HOUSE_CLOSED", function()
  ahOpen = false
  if state ~= "idle" then Abort("AH closed during scan") end
end)

-- Fires once when the list arrives, then again for every item cached afterwards.
-- Only the first one after our request matters.
ns.On("REPLICATE_ITEM_LIST_UPDATE", function()
  if state ~= "waiting" then return end
  local s = scan
  local n = C_AuctionHouse.GetNumReplicateItems()
  if n == 0 then
    -- Changed 2026-10-11 (beta T3): not what build 70338 does - a throttled call got no event at
    -- all (see the timeout in ns.Scan). Kept in case an empty reply shows up in another build.
    -- -- A throttled call returns an empty market, not an error.
    ns.db.throttled = (ns.db.throttled or 0) + 1
    return Abort("0 rows - throttled (15 min, account-wide) or empty house")
  end
  s.tReply = debugprofilestop()
  s.rec.n = n
  state = "processing"
  ProcessChunk(s)
end)
