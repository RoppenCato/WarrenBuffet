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

local _, ns = ...

local failed = false   -- one error per session is enough to know the API differs

local function Read()
  local T = C_TradeSkillUI
  if not (T and T.GetAllRecipeIDs and T.GetRecipeInfo and T.GetRecipeSchematic) then
    error("C_TradeSkillUI recipe functions are missing in this client")
  end
  -- Someone else's linked profession, or the guild's: not ours to record.
  if (T.IsTradeSkillLinked and T.IsTradeSkillLinked()) or (T.IsTradeSkillGuild and T.IsTradeSkillGuild()) then return end
  local prof = (T.GetChildProfessionInfo and T.GetChildProfessionInfo()) or (T.GetBaseProfessionInfo and T.GetBaseProfessionInfo())
  local profession = prof and (prof.parentProfessionName or prof.professionName)
  if not profession or profession == "" then return end
  local basic = Enum and Enum.CraftingReagentType and Enum.CraftingReagentType.Basic or 1

  local out, n = {}, 0
  for _, recipeID in ipairs(T.GetAllRecipeIDs() or {}) do
    local info = T.GetRecipeInfo(recipeID)
    if info and info.learned then
      local schematic = T.GetRecipeSchematic(recipeID, false) or {}
      local reagents = {}
      for _, slot in ipairs(schematic.reagentSlotSchematics or {}) do
        local first = slot.reagents and slot.reagents[1]
        if slot.reagentType == basic and first and first.itemID then
          reagents[#reagents + 1] = first.itemID .. ":" .. (slot.quantityRequired or 1)
        end
      end
      local cooldown = T.GetRecipeCooldown and T.GetRecipeCooldown(recipeID) or 0
      n = n + 1
      out[n] = table.concat({ recipeID, schematic.outputItemID or 0, schematic.quantityMin or 1,
        schematic.quantityMax or 1, math.floor(cooldown or 0), table.concat(reagents, ","), info.name or "" }, "\t")
    end
  end
  if n == 0 then return end   -- the list is not loaded yet; TRADE_SKILL_LIST_UPDATE comes again

  local mine = ns.db.recipes[ns.char]
  if not mine then
    mine = {}
    ns.db.recipes[ns.char] = mine
  end
  local list = table.concat(out, "\n") .. "\n"
  local changed = not mine[profession] or mine[profession].list ~= list
  mine[profession] = { ts = GetServerTime(), skill = prof.skillLevel or 0, max = prof.maxSkillLevel or 0, list = list }
  if changed then ns.Note("%s: %d recipes saved for the planner", profession, n) end
end

local queued = false
local function Queue()
  if queued or failed or not ns.char then return end
  queued = true
  C_Timer.After(1, function()   -- the list update comes in bursts
    queued = false
    local ok, err = pcall(Read)
    if not ok then
      failed = true
      ns.Error("recipes", err)
    end
  end)
end

ns.On("TRADE_SKILL_SHOW", Queue)
ns.On("TRADE_SKILL_LIST_UPDATE", Queue)
ns.On("NEW_RECIPE_LEARNED", Queue)
