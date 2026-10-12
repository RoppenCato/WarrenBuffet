-- Recipes: what each character can craft, and from what. Read when a profession window is open.
-- With scan prices this gives the planner its Craft list: materials cost against what the
-- product sells for. Read-only - nothing is crafted or queued.
--
--   ForeverAHDB.recipes[char][profession] = {
--     ts = server time, skill = n, max = n,
--     list = "recipeID\toutputItemID\tmin\tmax\tcooldownSeconds\treagentID:qty,...\tname\n..."
--   }
-- Only learned recipes. Only the fixed (basic) reagents - optional ones are left out.
-- outputItemID 0 = the recipe makes no item (most enchants); the planner skips those.
-- cooldownSeconds = time left on a timed craft when the window was read, 0 if ready or untimed.
--
-- Changed 2026-10-12 (beta run 4): with Tailoring and Enchanting open, nothing was saved and no
-- error was raised - the modern reader returned quietly and left no trace of why. So:
--   * every attempt now leaves a line in ForeverAHDB.probe.recipes saying what each API answered
--   * the Classic profession API (trade skill window) and the Classic enchanting API ("craft"
--     window) are tried when the modern one gives nothing - a Classic-style client may use those
--   * the window is read at once and again a second later, not only after a second
--   * /fah recipes reads the open window now and prints the probe line

local _, ns = ...

local failed = false   -- one error per session is enough to know the API differs

local function Line(recipeID, itemID, low, high, cooldown, reagents, name)
  return table.concat({ recipeID, itemID or 0, low or 1, high or low or 1, math.floor(cooldown or 0),
    table.concat(reagents, ","), name or "" }, "\t")
end

local function ItemID(link)
  return link and tonumber(link:match("item:(%d+)"))
end

-- Added 2026-10-12 (beta run 5): a profession info only counts if it has a name.
local function Named(info)
  return info and info.professionName and info.professionName ~= "" and info or nil
end

-- The Mainline API. Returns profession, skill, max, lines, and a note for the probe.
local function ReadModern()
  local T = C_TradeSkillUI
  if not (T and T.GetAllRecipeIDs and T.GetRecipeInfo and T.GetRecipeSchematic) then return nil, nil, nil, {}, "modern: no API" end
  -- Someone else's linked profession, or the guild's: not ours to record.
  if (T.IsTradeSkillLinked and T.IsTradeSkillLinked()) or (T.IsTradeSkillGuild and T.IsTradeSkillGuild()) then
    return nil, nil, nil, {}, "modern: linked or guild window"
  end
  -- Changed 2026-10-12 (beta run 5): the probe showed 261 recipes, 5 of them learned, and an
  -- empty profession name with id 0. Forever has no "child" professions, so the child call
  -- answers with an empty record - and because that record is not nil, the base profession was
  -- never asked. Now: child if it has a name, else base, else the profession of a learned recipe.
  -- local prof = (T.GetChildProfessionInfo and T.GetChildProfessionInfo()) or (T.GetBaseProfessionInfo and T.GetBaseProfessionInfo())
  -- local profession = prof and (prof.parentProfessionName or prof.professionName)
  local source = "child"
  local prof = Named(T.GetChildProfessionInfo and T.GetChildProfessionInfo())
  if not prof then
    source, prof = "base", Named(T.GetBaseProfessionInfo and T.GetBaseProfessionInfo())
  end
  local basic = Enum and Enum.CraftingReagentType and Enum.CraftingReagentType.Basic or 1
  local ids = T.GetAllRecipeIDs() or {}
  local out = {}
  local firstLearned   -- added 2026-10-12: to ask which profession a learned recipe belongs to
  for _, recipeID in ipairs(ids) do
    local info = T.GetRecipeInfo(recipeID)
    if info and info.learned then
      firstLearned = firstLearned or recipeID
      local schematic = T.GetRecipeSchematic(recipeID, false) or {}
      local reagents = {}
      for _, slot in ipairs(schematic.reagentSlotSchematics or {}) do
        local first = slot.reagents and slot.reagents[1]
        if slot.reagentType == basic and first and first.itemID then
          reagents[#reagents + 1] = first.itemID .. ":" .. (slot.quantityRequired or 1)
        end
      end
      out[#out + 1] = Line(recipeID, schematic.outputItemID, schematic.quantityMin, schematic.quantityMax,
        T.GetRecipeCooldown and T.GetRecipeCooldown(recipeID), reagents, info.name)
    end
  end
  -- local note = ("modern: profession=%s id=%s recipes=%d learned=%d"):format(tostring(profession),
  --   tostring(prof and prof.professionID), #ids, #out)
  -- if not profession or profession == "" then return nil, nil, nil, {}, note end
  -- return profession, prof.skillLevel, prof.maxSkillLevel, out, note
  if not prof and firstLearned then
    source, prof = "recipe", Named(T.GetProfessionInfoByRecipeID and T.GetProfessionInfoByRecipeID(firstLearned))
  end
  local profession = prof and ((prof.parentProfessionName and prof.parentProfessionName ~= "" and prof.parentProfessionName)
    or prof.professionName)
  if not profession and firstLearned then
    -- Recipes without a name for their profession are still worth having; the key only has to
    -- keep two professions apart.
    source, profession = "none", "Profession " .. firstLearned
  end
  local note = ("modern: profession=%s (from %s) id=%s recipes=%d learned=%d"):format(tostring(profession), source,
    tostring(prof and prof.professionID), #ids, #out)
  if not profession then return nil, nil, nil, {}, note end
  return profession, prof and prof.skillLevel, prof and prof.maxSkillLevel, out, note
end

-- The Classic trade skill window (everything but enchanting in Classic clients).
local function ReadClassic()
  if not (GetNumTradeSkills and GetTradeSkillInfo and GetTradeSkillLine) then return nil, nil, nil, {}, "classic: no API" end
  local profession, skill, max = GetTradeSkillLine()
  local count = GetNumTradeSkills() or 0
  local out = {}
  for i = 1, count do
    local name, kind = GetTradeSkillInfo(i)
    if name and kind ~= "header" and kind ~= "subheader" then
      local reagents = {}
      for r = 1, GetTradeSkillNumReagents(i) or 0 do
        local _, _, needed = GetTradeSkillReagentInfo(i, r)
        local id = ItemID(GetTradeSkillReagentItemLink(i, r))
        if id then reagents[#reagents + 1] = id .. ":" .. (needed or 1) end
      end
      local low, high = GetTradeSkillNumMade(i)
      local link = GetTradeSkillRecipeLink and GetTradeSkillRecipeLink(i)
      out[#out + 1] = Line(link and tonumber(link:match("enchant:(%d+)")) or i, ItemID(GetTradeSkillItemLink(i)),
        low, high, GetTradeSkillCooldown and GetTradeSkillCooldown(i), reagents, name)
    end
  end
  local note = ("classic: profession=%s rows=%d recipes=%d"):format(tostring(profession), count, #out)
  if not profession or profession == "" or profession == "UNKNOWN" then return nil, nil, nil, {}, note end
  return profession, skill, max, out, note
end

-- The Classic "craft" window (enchanting in Classic clients).
local function ReadCraft()
  if not (GetNumCrafts and GetCraftInfo and GetCraftDisplaySkillLine) then return nil, nil, nil, {}, "craft: no API" end
  local profession, skill, max = GetCraftDisplaySkillLine()
  local count = GetNumCrafts() or 0
  local out = {}
  for i = 1, count do
    local name, _, kind = GetCraftInfo(i)
    if name and kind ~= "header" then
      local reagents = {}
      for r = 1, GetCraftNumReagents(i) or 0 do
        local _, _, needed = GetCraftReagentInfo(i, r)
        local id = ItemID(GetCraftReagentItemLink(i, r))
        if id then reagents[#reagents + 1] = id .. ":" .. (needed or 1) end
      end
      local link = GetCraftItemLink and GetCraftItemLink(i)
      out[#out + 1] = Line(link and tonumber(link:match("enchant:(%d+)")) or i, ItemID(link), 1, 1, 0, reagents, name)
    end
  end
  local note = ("craft: profession=%s rows=%d recipes=%d"):format(tostring(profession), count, #out)
  if not profession or profession == "" then return nil, nil, nil, {}, note end
  return profession, skill, max, out, note
end

local function Save(profession, skill, max, out)
  local mine = ns.db.recipes[ns.char]
  if not mine then
    mine = {}
    ns.db.recipes[ns.char] = mine
  end
  local list = table.concat(out, "\n") .. "\n"
  local changed = not mine[profession] or mine[profession].list ~= list
  mine[profession] = { ts = GetServerTime(), skill = skill or 0, max = max or 0, list = list }
  if changed then ns.Note("%s: %d recipes saved for the planner", profession, #out) end
end

-- Reads whatever profession window is open, with whichever API answers. Returns the probe line.
local function Read(trigger)
  local notes = {}
  for _, reader in ipairs({ ReadModern, ReadClassic, ReadCraft }) do
    local profession, skill, max, out, note = reader()
    notes[#notes + 1] = note
    if profession and #out > 0 then Save(profession, skill, max, out) end
  end
  local probe = GetServerTime() .. " " .. trigger .. " | " .. table.concat(notes, " | ")
  ns.db.probe = ns.db.probe or {}
  -- Changed 2026-10-12 (beta run 5): keep the last eight, not just the last. The one line that
  -- survived was written by a timer a second before /reload, not by the command the user typed.
  -- ns.db.probe.recipes = probe
  local history = type(ns.db.probe.recipes) == "table" and ns.db.probe.recipes or {}
  history[#history + 1] = probe
  while #history > 8 do table.remove(history, 1) end
  ns.db.probe.recipes = history
  return probe
end

local function Guarded(trigger)
  if failed or not ns.char then return end
  local ok, result = pcall(Read, trigger)
  if not ok then
    failed = true
    ns.Error("recipes", result)
  end
  return ok and result
end

local queued = false
local function OnEvent(event)
  return function()
    Guarded(event)
    if queued then return end
    queued = true
    C_Timer.After(1, function()   -- the list can arrive after the window; look again
      queued = false
      Guarded(event .. "+1s")
    end)
  end
end

for _, event in ipairs({ "TRADE_SKILL_SHOW", "TRADE_SKILL_LIST_UPDATE", "TRADE_SKILL_UPDATE", "NEW_RECIPE_LEARNED",
                         "CRAFT_SHOW", "CRAFT_UPDATE" }) do
  ns.On(event, OnEvent(event))
end

-- /fah recipes: read the open profession window now and show what each API answered.
function ns.ReadRecipes()
  failed = false
  local probe = Guarded("/fah recipes")
  ns.Print("%s", probe or "recipes: reading failed - the error is saved in the file")
end
