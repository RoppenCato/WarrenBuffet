-- Plan: shows the plan the pipeline wrote (ForeverAH_Plan.lua) - what to sell, what to do with
-- your auctions, what to buy, each with its reason - and adds a price line to item tooltips.
-- Display only: it suggests, the player clicks.
--
-- The game reads the plan file at login and on /reload, so the plan is as fresh as the last
-- dashboard build before that. The dashboard is the live view.

local _, ns = ...

local GOLD, SOFT, WHITE = "|cffffd100", "|cffa8a8a8", "|cffffffff"
local plan = ForeverAH_Plan   -- nil until the pipeline has written one

local function Section(lines, title, rows, describe)
  if not rows or #rows == 0 then return end
  lines[#lines + 1] = " "
  lines[#lines + 1] = GOLD .. title .. "|r"
  for _, r in ipairs(rows) do
    lines[#lines + 1] = ("%s%s|r  %s%s"):format(WHITE, r.act, r.item, describe(r))
    lines[#lines + 1] = "    " .. SOFT .. r.why .. "|r"
  end
end

local function Lines()
  if type(plan) ~= "table" then
    return { "No plan yet.", " ", SOFT .. "Scan the auction house, /reload, press Refresh on the dashboard," .. "|r",
             SOFT .. "then /reload once more. The plan is written by the dashboard." .. "|r" }
  end
  local lines = {}
  local newest = ns.db.scans[#ns.db.scans]
  lines[#lines + 1] = ("%sPlan from %s|r, built on the scan of %s"):format(GOLD, date("%H:%M", plan.made), date("%H:%M", plan.scan))
  if newest and newest.ts > plan.scan then
    lines[#lines + 1] = SOFT .. "A newer scan exists: Refresh the dashboard, then /reload." .. "|r"
  end
  if plan.headline and plan.headline ~= "" then lines[#lines + 1] = plan.headline end
  Section(lines, "Sell", plan.sell, function(r)
    return " x" .. r.units .. (r.price > 0 and "  at " .. ns.Money(r.price) or "") .. (r.get > 0 and "  ->  " .. ns.Money(r.get) or "")
  end)
  Section(lines, "Craft", plan.craft, function(r)   -- added 2026-10-11 (v0.9)
    return (r.units > 0 and "  (you can make " .. r.units .. ")" or "") .. "  +" .. ns.Money(r.profit) .. " each, materials " .. ns.Money(r.cost)
  end)
  Section(lines, "Your auctions", plan.auctions, function(r)
    return " x" .. r.units .. "  yours " .. ns.Money(r.price) .. (r.cheapest > 0 and ", cheapest " .. ns.Money(r.cheapest) or "")
  end)
  Section(lines, "Buy", plan.buy, function(r)
    return " x" .. r.units .. "  at " .. ns.Money(r.max) .. " or less  (" .. ns.Money(r.cost) .. " for +" .. ns.Money(r.profit) .. ")"
  end)
  if #lines <= 3 then lines[#lines + 1] = SOFT .. "Nothing to do right now." .. "|r" end
  return lines
end

ns.On("PLAYER_LOGIN", function()
  if ns.SetPlan then ns.SetPlan(Lines(), type(plan) == "table") end
end)

---------------------------------------------------------------------------------------------
-- Tooltip: cheapest listing in the scan the plan was built on, vendor price, and the plan's word.

local function AddToTooltip(tooltip, itemID)
  if type(plan) ~= "table" or not itemID then return end
  local cheapest = plan.min and plan.min[itemID]
  local action = plan.act and plan.act[itemID]
  if not cheapest and not action then return end
  if cheapest then
    local GetInfo = C_Item and C_Item.GetItemInfo or GetItemInfo
    local vendor = GetInfo and select(11, GetInfo(itemID))
    tooltip:AddDoubleLine("AH cheapest", ns.Money(cheapest), 1, 0.82, 0, 1, 1, 1)
    if vendor and vendor > 0 then tooltip:AddDoubleLine("Vendor pays", ns.Money(vendor), 1, 0.82, 0, 1, 1, 1) end
  end
  if action then tooltip:AddDoubleLine("ForeverAH plan", action, 1, 0.82, 0, 1, 1, 1) end
end

-- pcall: a tooltip error would repeat on every mouse-over, so it is recorded once and dropped.
local failed = false
local function Safe(tooltip, itemID)
  if failed then return end
  local ok, err = pcall(AddToTooltip, tooltip, itemID)
  if not ok then
    failed = true
    ns.Error("tooltip", err)
  end
end

if TooltipDataProcessor and Enum and Enum.TooltipDataType then
  TooltipDataProcessor.AddTooltipPostCall(Enum.TooltipDataType.Item, function(tooltip, data)
    if data and data.id then Safe(tooltip, data.id) end
  end)
elseif GameTooltip and GameTooltip.HookScript then   -- clients without the tooltip data system
  GameTooltip:HookScript("OnTooltipSetItem", function(tooltip)
    local _, link = tooltip:GetItem()
    Safe(tooltip, link and tonumber(link:match("item:(%d+)")))
  end)
end
