-- Minimal fake of the WoW API surface ForeverAH touches. Driven by tests/test_addon.py.
-- Not a model of the real client: it encodes what the docs/wiki say, so passing here proves
-- the addon's logic, not that Forever behaves this way. That is what T3-T6 are for.

local now, clock = 1760180000, 0   -- server time (s), frame clock (ms)
-- Changed 2026-10-11: frames are widgets now (see Widget below); the single handler is gone.
-- local timers, handler, registered = {}, nil, {}
local timers = {}
local replicated, lastReplicate = {}, -1e9

UNKNOWN_EVENTS = {}   -- events RegisterEvent should reject
PRINTED = {}          -- every message, chat and window, in order
CHAT = {}             -- what went to the chat frame via print()
WINDOW = {}           -- what went to the addon's own window
AUCTIONS = {}         -- { {itemID, count, buyout, minBid, bid, hasAllInfo, timeLeft}, ... }
REPLICATE_CALLS = 0
INBOX = {}            -- { {subject=, money=, expires=, invoice=, name=, bid=, ...}, ... }
MONEY = 123456
NS = {}

function print(...)
  local t = {}
  for i = 1, select("#", ...) do t[#t + 1] = tostring((select(i, ...))) end
  PRINTED[#PRINTED + 1] = table.concat(t, " ")
  CHAT[#CHAT + 1] = PRINTED[#PRINTED]
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

-- Changed 2026-10-11 for UI.lua: widgets only have the methods listed here, and raise on any
-- other name. The first stub accepted every call, which is how a wrong API call reached the
-- beta (GetItemCommodityStatus). The lists are the real method names the addon uses.
-- function CreateFrame()
--   local f = {}
--   function f:RegisterEvent(event)
--     if UNKNOWN_EVENTS[event] then error("Attempt to register unknown event " .. event) end
--     registered[event] = true
--   end
--   function f:SetScript(_, fn) handler = fn end
--   return f
-- end
--
-- function Fire(event, ...)
--   if registered[event] then handler(nil, event, ...) end
-- end
-- Changed 2026-10-11 (UI v0.7): more real method names (minimap button, bordered window), and
-- the two Blizzard templates the window may use. Still strict: anything else raises.
-- local REGION = "SetPoint ClearAllPoints GetPoint SetAllPoints SetSize Show Hide IsShown SetShown"
-- local FRAME = REGION .. " RegisterEvent SetScript SetMovable EnableMouse RegisterForDrag StartMoving"
--   .. " StopMovingOrSizing CreateTexture CreateFontString SetFrameStrata SetClampedToScreen EnableMouseWheel"
-- local METHODS = {
--   Frame = FRAME,
--   Button = FRAME .. " RegisterForClicks",
--   ScrollingMessageFrame = FRAME .. " AddMessage SetFontObject SetJustifyH SetFading SetMaxLines ScrollUp ScrollDown",
--   Texture = REGION .. " SetColorTexture",
--   FontString = REGION .. " SetText SetJustifyH",
--   GameTooltip = "SetOwner SetText AddLine Show Hide",
-- }
-- local FONTS = { GameFontNormal = true, GameFontNormalSmall = true }
local REGION = "SetPoint ClearAllPoints GetPoint SetAllPoints SetSize SetWidth SetHeight GetWidth GetCenter"
  .. " Show Hide IsShown SetShown"
local FRAME = REGION .. " RegisterEvent SetScript SetMovable EnableMouse RegisterForDrag StartMoving"
  .. " StopMovingOrSizing CreateTexture CreateFontString SetFrameStrata SetFrameLevel SetToplevel Raise"
  .. " SetClampedToScreen EnableMouseWheel GetEffectiveScale"
local METHODS = {
  Frame = FRAME,
  Button = FRAME .. " RegisterForClicks SetHighlightTexture",
  -- 2026-10-11 (v0.8): Clear, ScrollToTop, SetTextColor, AddDoubleLine added for the plan view
  ScrollingMessageFrame = FRAME .. " AddMessage SetFontObject SetJustifyH SetFading SetMaxLines ScrollUp ScrollDown"
    .. " Clear ScrollToTop",
  Texture = REGION .. " SetColorTexture SetTexture SetTexCoord",
  FontString = REGION .. " SetText SetJustifyH SetTextColor",
  GameTooltip = "SetOwner SetText AddLine AddDoubleLine Show Hide",
}
local TEMPLATES = { BackdropTemplate = " SetBackdrop SetBackdropColor SetBackdropBorderColor", UIPanelCloseButton = "" }
local FONTS = { GameFontNormal = true, GameFontNormalSmall = true, GameFontHighlightSmall = true, NumberFontNormalSmall = true }
NO_TEMPLATES = false   -- true: this client has none of the templates (tests the plain window)
local widgets = {}
BROKEN_WIDGET = nil   -- a widget kind CreateFrame should fail for, to test the chat fallback

local impl = {}
function impl:RegisterEvent(event)
  if UNKNOWN_EVENTS[event] then error("Attempt to register unknown event " .. event) end
  self.events[event] = true
end
function impl:SetScript(name, fn) self.scripts[name] = fn end
-- Changed 2026-10-11: showing a hidden widget runs its OnShow script, as in the game.
-- function impl:Show() self.shown = true end
-- function impl:Hide() self.shown = false end
-- function impl:SetShown(show) self.shown = show and true or false end
function impl:SetShown(show)
  local was = self.shown
  self.shown = show and true or false
  if self.shown and not was and self.scripts.OnShow then self.scripts.OnShow(self) end
end
function impl:Show() self:SetShown(true) end
function impl:Hide() self:SetShown(false) end
function impl:Raise() self.raised = self.raised + 1 end
function impl:SetSize(width, height) self.width, self.height = width, height end
function impl:GetWidth() return self.width end
function impl:GetCenter() return 500, 500 end
function impl:GetEffectiveScale() return 1 end
function impl:IsShown() return self.shown end
function impl:SetText(text) self.text = text end
function impl:ClearAllPoints() self.point = nil end
function impl:SetPoint(point, relativeTo, relativePoint, x, y) self.point = { point, relativeTo, relativePoint, x, y } end
function impl:GetPoint() return unpack(self.point, 1, 5) end
-- Changed 2026-10-11 (v0.8): every message frame keeps its own lines; only the log (the last
-- one the window creates, named below) also feeds WINDOW and PRINTED.
-- function impl:AddMessage(text)
--   WINDOW[#WINDOW + 1] = text
--   PRINTED[#PRINTED + 1] = text
-- end
function impl:AddMessage(text)
  self.lines[#self.lines + 1] = text
  if self.isPlan then return end
  WINDOW[#WINDOW + 1] = text
  PRINTED[#PRINTED + 1] = text
end
function impl:Clear() self.lines = {} end
function impl:AddLine(text) self.lines[#self.lines + 1] = text end
function impl:AddDoubleLine(left, right) self.lines[#self.lines + 1] = left .. ": " .. right end
function impl:CreateTexture() return Widget("Texture") end
function impl:CreateFontString(_, _, font)
  if not FONTS[font] then error("unknown font object " .. tostring(font)) end
  local fs = Widget("FontString")
  self.fontStrings[#self.fontStrings + 1] = fs   -- so tests can read a label
  return fs
end

-- function Widget(kind)   (2026-10-11: `extra` = methods a template adds)
function Widget(kind, extra)
  local allowed = {}
  -- for name in METHODS[kind]:gmatch("%S+") do allowed[name] = true end
  for name in (METHODS[kind] .. (extra or "")):gmatch("%S+") do allowed[name] = true end
  -- raised and width start with a value: a missing field would hit the strict check below
  local w = { kind = kind, scripts = {}, events = {}, fontStrings = {}, shown = true, raised = 0, width = 140,
              lines = {}, isPlan = false }
  widgets[#widgets + 1] = w
  return setmetatable(w, { __newindex = function(t, key, value)
    if key == "planLines" then value.isPlan = true end   -- the window names its plan view
    rawset(t, key, value)
  end, __index = function(_, name)
    if not allowed[name] then error(kind .. " has no method " .. tostring(name), 2) end
    return impl[name] or function() end
  end })
end

-- Changed 2026-10-11: two templates are known; any other name, or NO_TEMPLATES, raises.
-- function CreateFrame(kind, name, _, template)
--   if template then error("no Blizzard templates expected, got " .. tostring(template)) end
--   if kind == BROKEN_WIDGET then error("Couldn't create frame of type " .. kind) end
--   local w = Widget(kind)
--   if name then _G[name] = w end
--   return w
-- end
function CreateFrame(kind, name, parent, template)
  if template and (NO_TEMPLATES or not TEMPLATES[template]) then
    error("Couldn't find inherited node: " .. tostring(template))
  end
  if kind == BROKEN_WIDGET then error("Couldn't create frame of type " .. kind) end
  if parent == nil and select("#", name, parent) >= 2 and name == nil and kind ~= "Frame" then
    error("CreateFrame: no parent given for " .. kind)
  end
  local w = Widget(kind, template and TEMPLATES[template])
  w.parent = parent
  if name then _G[name] = w end
  return w
end

UIParent = Widget("Frame")
GameTooltip = Widget("GameTooltip")
-- Added 2026-10-11 (UI v0.7)
Minimap = Widget("Frame")              -- set to nil in a test for a client without one
AuctionHouseFrame = Widget("Frame")
CURSOR = { 600, 500 }
function GetCursorPosition() return CURSOR[1], CURSOR[2] end
function BreakUpLargeNumbers(n)
  local s = tostring(math.floor(n))
  while true do
    local changed
    s, changed = s:gsub("^(%d+)(%d%d%d)", "%1,%2")
    if changed == 0 then return s end
  end
end
-- Added 2026-10-11 (v0.8): item tooltips. ShowItemTooltip(id) returns the lines the addon added.
local tooltipCalls = {}
Enum = Enum or {}
Enum.TooltipDataType = { Item = 0 }
TooltipDataProcessor = { AddTooltipPostCall = function(kind, fn)
  if kind ~= Enum.TooltipDataType.Item then error("unexpected tooltip data type") end
  tooltipCalls[#tooltipCalls + 1] = fn
end }
function ShowItemTooltip(itemID)
  local tip = Widget("GameTooltip")
  for _, fn in ipairs(tooltipCalls) do fn(tip, { id = itemID }) end
  return tip.lines
end
function PlanLines() return ForeverAHWindow.planLines.lines end

C_CurrencyInfo = { GetCoinTextureString = function(copper)
  if type(copper) ~= "number" then error("bad argument #1 to 'GetCoinTextureString'") end
  local g, s, c = math.floor(copper / 10000), math.floor(copper / 100) % 100, copper % 100
  return (g > 0 and g .. "g " or "") .. ((g > 0 or s > 0) and s .. "s " or "") .. c .. "c"
end }
GameFontHighlightSmall = {}

function Fire(event, ...)
  for _, w in ipairs(widgets) do
    if w.events[event] and w.scripts.OnEvent then w.scripts.OnEvent(w, event, ...) end
  end
end

function RunScript(name, script, ...)   -- e.g. RunScript("ForeverAHButton", "OnClick", "LeftButton")
  local w = _G[name]
  return w.scripts[script](w, ...)
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
-- Added 2026-10-11 (beta T6): the clicks the ledger now observes.
function C_AuctionHouse.CancelAuction() end
function C_AuctionHouse.GetCancelCost() return 3 end
function C_AuctionHouse.ConfirmCommoditiesPurchase() end
function C_AuctionHouse.CalculateItemDeposit(_, duration) return 100 * duration end
function C_AuctionHouse.CalculateCommodityDeposit(_, _, quantity) return 7 * quantity end

C_Item = {
  DoesItemExist = function(item) return item.id ~= nil end,
  GetItemID = function(item) return item.id end,
  -- Changed 2026-10-11 (v0.9): also knows the items a test put in ITEM_INFO.
  -- GetItemNameByID = function(id) return ({ [2589] = "Linen Cloth", [2770] = "Copper Ore" })[id] end,
  GetItemNameByID = function(id)
    return ({ [2589] = "Linen Cloth", [2770] = "Copper Ore" })[id] or (ITEM_INFO[id] and ITEM_INFO[id][1])
  end,
}

-- Added 2026-10-11 for Items.lua. An item missing from ITEM_INFO is "not cached yet": nil.
ITEM_INFO = {}   -- id -> { name, vendorPrice, stack, classID, subclassID }
function C_Item.GetItemInfo(id)
  if type(id) ~= "number" then error("bad argument #1 to 'GetItemInfo'") end
  local it = ITEM_INFO[id]
  if not it then return nil end
  -- return it[1], "|Hitem:" .. id .. "|h", 1, 10, 1, "Trade Goods", "Cloth", it[3], "", 0, it[2], it[4], it[5], 0, 0, nil, true
  -- (2026-10-11, v0.9: optional 6th and 7th entries give quality and item level)
  return it[1], "|Hitem:" .. id .. "|h", it[6] or 1, it[7] or 10, 1, "Trade Goods", "Cloth", it[3], "", 0, it[2], it[4], it[5], 0, 0, nil, true
end

-- Added 2026-10-11 (v0.9) for Recipes.lua: the profession window's data, Mainline shape.
PROFESSION = { professionName = "Tailoring", skillLevel = 75, maxSkillLevel = 150 }
RECIPES = {}          -- { {id=, name=, learned=, output=, min=, max=, cooldown=, reagents={ {item, qty, type}, ... }}, ... }
TRADESKILL_LINKED = false
Enum = Enum or {}
Enum.CraftingReagentType = { Modifying = 0, Basic = 1, Finishing = 2 }
C_TradeSkillUI = {}
function C_TradeSkillUI.IsTradeSkillLinked() return TRADESKILL_LINKED end
function C_TradeSkillUI.IsTradeSkillGuild() return false end
function C_TradeSkillUI.GetChildProfessionInfo() return PROFESSION end
function C_TradeSkillUI.GetAllRecipeIDs()
  local ids = {}
  for i, r in ipairs(RECIPES) do ids[i] = r.id end
  return ids
end
local function recipe(id)
  if type(id) ~= "number" then error("bad argument #1: recipe id expected") end
  for _, r in ipairs(RECIPES) do if r.id == id then return r end end
end
function C_TradeSkillUI.GetRecipeInfo(id)
  local r = recipe(id)
  return r and { recipeID = r.id, name = r.name, learned = r.learned }
end
function C_TradeSkillUI.GetRecipeSchematic(id, isRecraft)
  if type(isRecraft) ~= "boolean" then error("bad argument #2: isRecraft expected") end
  local r = recipe(id)
  local slots = {}
  for i, g in ipairs(r.reagents) do
    slots[i] = { reagents = { { itemID = g[1] } }, quantityRequired = g[2], reagentType = g[3] or 1 }
  end
  return { recipeID = r.id, outputItemID = r.output, quantityMin = r.min or 1, quantityMax = r.max or 1, reagentSlotSchematics = slots }
end
function C_TradeSkillUI.GetRecipeCooldown(id) return recipe(id).cooldown end

AUCTION_EXPIRED_MAIL_SUBJECT = "Auction expired: %s"
AUCTION_REMOVED_MAIL_SUBJECT = "Auction cancelled: %s"
AUCTION_OUTBID_MAIL_SUBJECT = "Outbid on %s"

function GetInboxNumItems() return #INBOX, #INBOX end

-- Changed 2026-10-11 (beta T6): daysLeft is a snapshot taken when the inbox is refreshed from
-- the server, not a live countdown. The stub computed it live, which hid the double-logging.
-- function GetInboxHeaderInfo(i)
--   local m = INBOX[i]
--   return nil, nil, "Horde Auction House", m.subject, m.money or 0, 0, (m.expires - now) / 86400, m.item and 1 or nil
-- end
function RefreshInbox()
  for _, m in ipairs(INBOX) do m.daysLeft = (m.expires - now) / 86400 end
end

function GetInboxHeaderInfo(i)
  local m = INBOX[i]
  return nil, nil, "Horde Auction House", m.subject, m.money or 0, 0, m.daysLeft, m.item and 1 or nil
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

-- Added 2026-10-11 for Inventory.lua. Mainline bag layout; bank bags read as 0 slots while the
-- bank is closed, like the real client.
-- Changed 2026-10-11 (v0.8): Enum is shared with the tooltip stub above, so add to it.
-- Enum = { BagIndex = {
--   Backpack = 0, Bag_1 = 1, Bag_2 = 2, Bag_3 = 3, Bag_4 = 4, ReagentBag = 5,
--   CharacterBankTab_1 = 6, CharacterBankTab_2 = 7, AccountBankTab_1 = 12,
--   Characterbanktab = -2, Accountbanktab = -3, Keyring = -1,
-- } }
Enum = Enum or {}
Enum.BagIndex = {
  Backpack = 0, Bag_1 = 1, Bag_2 = 2, Bag_3 = 3, Bag_4 = 4, ReagentBag = 5,
  CharacterBankTab_1 = 6, CharacterBankTab_2 = 7, AccountBankTab_1 = 12,
  Characterbanktab = -2, Accountbanktab = -3, Keyring = -1,
}
BANK_OPEN = false
BAGS_READABLE = true
local containers = {}   -- bag -> { slots = n, [slot] = info }

function SetBag(bag, slots, items)   -- items: { {slot, itemID, count, isBound}, ... }
  local c = { slots = slots }
  for _, it in ipairs(items) do
    c[it[1]] = { itemID = it[2], stackCount = it[3], isBound = it[4] or false }
  end
  containers[bag] = c
end

C_Container = {}
function C_Container.GetContainerNumSlots(bag)
  if type(bag) ~= "number" then error("bad argument #1 to 'GetContainerNumSlots'") end
  local c = containers[bag]
  if not c or not BAGS_READABLE or (bag > 5 and not BANK_OPEN) then return 0 end
  return c.slots
end
function C_Container.GetContainerItemInfo(bag, slot) return containers[bag][slot] end

OWNED = {}
QUERY_OWNED = 0
function C_AuctionHouse.QueryOwnedAuctions(sorts)
  if type(sorts) ~= "table" then error("bad argument #1 to 'QueryOwnedAuctions'") end
  QUERY_OWNED = QUERY_OWNED + 1
end
function C_AuctionHouse.GetNumOwnedAuctions() return #OWNED end
function C_AuctionHouse.GetOwnedAuctionInfo(i) return OWNED[i] end
date = os.date

-- Changed 2026-10-11: the name can be missing early in a login (PLAYER_NAME = nil in a test).
-- function UnitName() return "Tester" end
PLAYER_NAME = "Tester"
-- function UnitName() return PLAYER_NAME end   (2026-10-11, v0.10: "npc" is the open vendor)
NPC_NAME = nil
function UnitName(unit)
  if unit == "npc" then return NPC_NAME end
  return PLAYER_NAME
end

-- Added 2026-10-11 (v0.10) for Vendors.lua: an open vendor window.
MERCHANT = {}   -- { {itemID, price, stack, available, extendedCost}, ... }
function GetMerchantNumItems() return #MERCHANT end
function GetMerchantItemID(index) return MERCHANT[index][1] end
C_MerchantFrame = { GetItemInfo = function(index)
  if type(index) ~= "number" then error("bad argument #1 to 'GetItemInfo'") end
  local m = MERCHANT[index]
  return { price = m[2], stackCount = m[3], numAvailable = m[4], hasExtendedCost = m[5] or false }
end }
ERRORS = {}
function geterrorhandler() return function(text) ERRORS[#ERRORS + 1] = text end end
function GetRealmName() return "Beta Realm" end
function GetNormalizedRealmName() return "BetaRealm" end
function UnitFactionGroup() return "Horde" end
function GetCurrentRegion() return 1 end
function GetRealZoneText() return "Orgrimmar" end
function GetBuildInfo() return "12.1.5", "99999", "Oct 1 2026", 120105 end
function GetMoney() return MONEY end
-- Added 2026-10-11 (beta run 2): balance changes arrive as PLAYER_MONEY.
function SetMoney(copper)
  MONEY = copper
  Fire("PLAYER_MONEY")
end
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
