-- Disenchant log: what each disenchant gave. Nobody has a yield table for Forever, so the planner
-- learns one from the player's own results: item quality and level in, materials out.
-- Observes only - it notices that the player disenchanted something, it disenchants nothing.
--
--   ForeverAHDB.disenchants[i] = "ts\titemID\tquality\titemLevel\tclassID\tmaterialID:qty,..."
--
-- How it knows: the bags are compared before the cast and after it. The one item that is gone
-- is what was disenchanted, and whatever there is more of is what it gave. A result is only
-- recorded when exactly one item went missing, so an unrelated bag change cannot be mistaken
-- for one.

local _, ns = ...

local DISENCHANT = 13262   -- spell id of Disenchant
local WAIT = 60            -- s to wait for the loot to reach the bags
local before, since

-- Every item in the carried bags, soulbound ones included (most disenchanted gear is).
local function Snapshot()
  local counts = {}
  for _, bag in ipairs(ns.CarriedBags or { 0, 1, 2, 3, 4 }) do
    for slot = 1, C_Container.GetContainerNumSlots(bag) or 0 do
      local info = C_Container.GetContainerItemInfo(bag, slot)
      if info and info.itemID then
        counts[info.itemID] = (counts[info.itemID] or 0) + (info.stackCount or 1)
      end
    end
  end
  return counts
end

local function Compare()
  if GetServerTime() - since > WAIT then
    before, since = nil, nil
    return
  end
  local after, lost, gained, names = Snapshot(), {}, {}, {}
  for id, n in pairs(before) do
    if (after[id] or 0) < n then lost[#lost + 1] = id end
  end
  for id, n in pairs(after) do
    local more = n - (before[id] or 0)
    if more > 0 then
      gained[#gained + 1] = id .. ":" .. more
      names[#names + 1] = (C_Item.GetItemNameByID and C_Item.GetItemNameByID(id) or "item " .. id) .. " x" .. more
    end
  end
  if #lost ~= 1 or #gained == 0 then return end   -- not finished yet, or not a clean result: keep waiting
  local GetInfo = C_Item.GetItemInfo or GetItemInfo
  local name, _, quality, level, _, _, _, _, _, _, _, classID = GetInfo(lost[1])
  table.sort(gained)
  ns.db.disenchants[#ns.db.disenchants + 1] = table.concat(
    { GetServerTime(), lost[1], quality or -1, level or 0, classID or -1, table.concat(gained, ",") }, "\t")
  ns.Note("Disenchanted %s: %s", name or ("item " .. lost[1]), table.concat(names, ", "))
  before, since = nil, nil
end

local function Guarded(fn)
  return function(...)
    local ok, err = pcall(fn, ...)
    if not ok then
      before, since = nil, nil
      ns.Error("disenchant", err)
    end
  end
end

ns.On("UNIT_SPELLCAST_START", Guarded(function(unit, _, spellID)
  if unit == "player" and spellID == DISENCHANT then before, since = Snapshot(), nil end
end))
ns.On("UNIT_SPELLCAST_SUCCEEDED", Guarded(function(unit, _, spellID)
  if unit == "player" and spellID == DISENCHANT and before then since = GetServerTime() end
end))
local function Cancel(unit, _, spellID)
  if unit == "player" and spellID == DISENCHANT and not since then before = nil end
end
ns.On("UNIT_SPELLCAST_INTERRUPTED", Cancel)
ns.On("UNIT_SPELLCAST_FAILED", Cancel)
ns.On("BAG_UPDATE_DELAYED", Guarded(function()
  if before and since then Compare() end
end))
