-- Vendors: what vendors charge, recorded whenever a vendor window is open.
-- The game tells an addon what a vendor PAYS for any item (Items.lua has that), but what a
-- vendor CHARGES is only visible at the vendor. Other addons ship a fixed list for this; there is
-- none for Forever, so this one is collected. Read-only - nothing is bought.
--
--   ForeverAHDB.vendors = "itemID\tprice\tstack\tavailable\tvendor\tzone\n..."
-- price = copper for one purchase of `stack` units. available = -1 for unlimited stock, otherwise
-- how many were left when last seen (limited-stock items are the ones worth reselling).
-- One line per item: the latest vendor seen selling it. Items bought with anything other than
-- money are left out.

local _, ns = ...

local lines   -- itemID -> line, from the saved string on first use

local function Lines()
  if not lines then
    lines = {}
    for line in (ns.db.vendors or ""):gmatch("([^\n]+)\n") do
      lines[tonumber(line:match("^(%d+)\t"))] = line
    end
  end
  return lines
end

-- price, stack, available, costs something other than money
local function Info(index)
  if C_MerchantFrame and C_MerchantFrame.GetItemInfo then
    local info = C_MerchantFrame.GetItemInfo(index)
    if info then return info.price, info.stackCount, info.numAvailable, info.hasExtendedCost end
  elseif GetMerchantItemInfo then
    local _, _, price, stack, available, _, _, extended = GetMerchantItemInfo(index)
    return price, stack, available, extended
  end
end

local function Read()
  local known, new, changed = Lines(), 0, false
  local vendor, zone = UnitName("npc") or "a vendor", GetRealZoneText() or ""
  for index = 1, GetMerchantNumItems() or 0 do
    local itemID = GetMerchantItemID(index)
    local price, stack, available, extended = Info(index)
    if itemID and price and price > 0 and not extended then
      local line = table.concat({ itemID, price, stack or 1, available or -1, vendor, zone }, "\t")
      if known[itemID] ~= line then
        if not known[itemID] then new = new + 1 end
        known[itemID], changed = line, true
      end
    end
  end
  if not changed then return end
  local ids, out = {}, {}
  for itemID in pairs(known) do ids[#ids + 1] = itemID end
  table.sort(ids)
  for i, itemID in ipairs(ids) do out[i] = known[itemID] end
  ns.db.vendors = table.concat(out, "\n") .. "\n"
  if new > 0 then ns.Note("%s: %d vendor prices saved", vendor, new) end
end

local queued, failed = false, false
local function Queue()
  if queued or failed then return end
  queued = true
  C_Timer.After(0.5, function()   -- the list fills in just after the window opens
    queued = false
    local ok, err = pcall(Read)
    if not ok then
      failed = true
      ns.Error("vendors", err)
    end
  end)
end

ns.On("MERCHANT_SHOW", Queue)
ns.On("MERCHANT_UPDATE", Queue)
