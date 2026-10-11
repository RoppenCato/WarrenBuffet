-- Items: a reference table of every item seen in a scan - name, vendor price, stack size, class.
-- With it the pipeline knows what a vendor pays (the price floor, and listings below it are free
-- money) and what things are called, without asking an outside source. Read-only.
--
-- Changed 2026-10-11 (v0.9): quality and item level added, for valuing gear by what it
-- disenchants into. The old six-field lines are dropped once and collected again (itemsV = 2).
-- --   ForeverAHDB.items = "itemID\tvendor\tstack\tclassID\tsubclassID\tname\n..."
--   ForeverAHDB.items = "itemID\tvendor\tstack\tclassID\tsubclassID\tquality\titemLevel\tname\n..."
-- vendor = what a vendor pays for one unit, in copper (0 = vendors do not buy it).
-- An item is added once, the first time the client has its data; items it has not loaded yet
-- are tried again after the next scan.

local _, ns = ...

local CHUNK = 500   -- items per frame
local RETRY = 20    -- s after a scan before looking again (added 2026-10-11, see ns.RecordItems)
local known         -- itemID -> true for what is already in the saved string

local function Known()
  if not known then
    if ns.db.itemsV ~= 2 then   -- lines from before v0.9 lack quality and item level
      ns.db.items, ns.db.itemsV = "", 2
    end
    known = {}
    for id in (ns.db.items or ""):gmatch("(%d+)\t[^\n]*\n") do known[tonumber(id)] = true end
  end
  return known
end

-- Changed 2026-10-11 (beta run 3): one pass right after a scan caught only 937 of 3,128 items,
-- because the client is still loading item data at that moment. The pass is now a local
-- function that ns.RecordItems runs twice more: 20 s later, and when the AH closes.
-- -- ids: the distinct item ids of a finished scan
-- function ns.RecordItems(ids)
local function Pass(ids)
  local GetInfo = C_Item and C_Item.GetItemInfo or GetItemInfo
  if not GetInfo then return end
  local have, added, i = Known(), 0, 1

  local function Step()
    local out, n = {}, 0
    for k = i, math.min(i + CHUNK - 1, #ids) do
      local id = ids[k]
      if not have[id] then
        -- local name, _, _, _, _, _, _, stack, _, _, vendor, classID, subclassID = GetInfo(id)
        local name, _, quality, level, _, _, _, stack, _, _, vendor, classID, subclassID = GetInfo(id)
        if name then
          have[id] = true
          n = n + 1
          -- out[n] = table.concat({ id, vendor or 0, stack or 1, classID or -1, subclassID or -1, name }, "\t")
          out[n] = table.concat({ id, vendor or 0, stack or 1, classID or -1, subclassID or -1, quality or -1,
            level or 0, name }, "\t")
        end
      end
    end
    if n > 0 then
      ns.db.items = (ns.db.items or "") .. table.concat(out, "\n") .. "\n"
      added = added + n
    end
    i = i + CHUNK
    return i <= #ids
  end

  -- Errors here must not look like a failed scan (it is already saved), so every chunk is
  -- protected and a failure only ends this pass.
  local function Run()
    local ok, more = pcall(Step)
    if not ok then
      ns.Error("items", more)
    elseif more then
      C_Timer.After(0, Run)
    elseif added > 0 then
      ns.Note("item reference: %d new items", added)
    end
  end
  Run()
end

local lastIds   -- the ids of the newest scan

-- ids: the distinct item ids of a finished scan
function ns.RecordItems(ids)
  lastIds = ids
  Pass(ids)
  C_Timer.After(RETRY, function()
    if lastIds == ids then Pass(ids) end
  end)
end

ns.On("AUCTION_HOUSE_CLOSED", function()
  if lastIds then Pass(lastIds) end
end)
