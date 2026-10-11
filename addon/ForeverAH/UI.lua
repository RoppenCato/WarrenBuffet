-- UI: the addon's own window, and a minimap button to open it. Display only.
--
-- Redesigned 2026-10-11 (v0.7) after the first real use:
--   * the window sat behind the auction house -> it is now in the HIGH strata, raises itself
--     when shown, and by default opens beside the AH window instead of under it
--   * the floating "FAH" button -> a round button on the minimap edge (drag it around the rim)
--   * plain black box -> bordered panel with a title bar, a status line (last scan, next scan)
--     and a proper close button
-- The first version's plain window and floating button are still here as fallbacks, used when
-- this client lacks a template or the minimap: BuildPlainWindow and BuildFloatingButton.
-- If no window can be built at all, messages go to chat and the reason is saved in
-- ForeverAHDB.uiErr.
--
--   left-click the button    open / close the window
--   right-click the button   quiet mode on/off: in quiet mode the window never opens by itself
--   drag                     move the button along the minimap, or the window anywhere
-- The window opens by itself for scan messages and /fah. Ledger lines never open it; while it
-- is closed the button shows how many are unread. State is saved in ForeverAHDB.ui.

local _, ns = ...

local MAX_LINES = 200
local THROTTLE = 15 * 60
local GREY, SOFT = "|cff8c8c8c", "|cffc8c8c8"
local window, log, status, button, count
local onMinimap = false
local unread = 0

local function SetCount()
  if not count then return end
  if onMinimap then
    count:SetText(unread > 0 and tostring(unread) or "")
  else
    count:SetText(unread > 0 and ("FAH " .. unread) or "FAH")
  end
end

-- One line on where the data stands: shown under the title and in the button's tooltip.
local function StatusText()
  local scans = ns.db and ns.db.scans
  local rec = scans and scans[#scans]
  if not rec then return "No scan yet - open the auction house" end
  local wait = THROTTLE - (GetServerTime() - rec.ts)
  return ("Last scan %s  -  %s auctions, %s items  -  %s"):format(date("%H:%M", rec.ts), ns.Number(rec.rows),
    ns.Number(rec.items), wait > 0 and ("next in " .. math.ceil(wait / 60) .. " min") or "ready to scan")
end

local function SavePoint(key, frame)
  local point, _, relativePoint, x, y = frame:GetPoint(1)
  ns.db.ui[key] = { point, relativePoint, math.floor(x + 0.5), math.floor(y + 0.5) }
end

local function RestorePoint(key, frame)
  local p = ns.db.ui[key]
  if p then
    frame:ClearAllPoints()
    frame:SetPoint(p[1], UIParent, p[2], p[3], p[4])
  end
end

local function Background(frame, alpha)
  local texture = frame:CreateTexture(nil, "BACKGROUND")
  texture:SetAllPoints()
  texture:SetColorTexture(0, 0, 0, alpha)
end

local function Draggable(frame, key)
  frame:SetMovable(true)
  frame:SetClampedToScreen(true)
  frame:EnableMouse(true)
  frame:RegisterForDrag("LeftButton")
  frame:SetScript("OnDragStart", function(self) self:StartMoving() end)
  frame:SetScript("OnDragStop", function(self)
    self:StopMovingOrSizing()
    SavePoint(key, self)
  end)
end

function ns.ShowWindow(show)
  if not window then return end
  window:SetShown(show)
  if ns.db then ns.db.ui.shown = show end
  if show then
    unread = 0
    SetCount()
  end
end

-- Adds a line to the window. Returns false when there is no window, so the caller can fall
-- back to chat. quiet = true: never open the window for this line.
function ns.Log(msg, quiet)
  if not log then return false end
  log:AddMessage(GREY .. date("%H:%M") .. "|r  " .. (quiet and SOFT .. msg .. "|r" or msg))
  if not window:IsShown() then
    if quiet or (ns.db and ns.db.ui.quiet) then
      unread = unread + 1
      SetCount()
    else
      ns.ShowWindow(true)
    end
  end
  return true
end

---------------------------------------------------------------------------------------------
-- Window

local function AddLog(frame, top)
  local lines = CreateFrame("ScrollingMessageFrame", nil, frame)
  lines:SetPoint("TOPLEFT", frame, "TOPLEFT", 12, top)
  lines:SetPoint("BOTTOMRIGHT", frame, "BOTTOMRIGHT", -12, 10)
  lines:SetFontObject(GameFontHighlightSmall)
  lines:SetJustifyH("LEFT")
  lines:SetFading(false)
  lines:SetMaxLines(MAX_LINES)
  lines:EnableMouseWheel(true)
  lines:SetScript("OnMouseWheel", function(self, delta)
    if delta > 0 then self:ScrollUp() else self:ScrollDown() end
  end)
  return lines
end

-- The first version's look: a black box with a text "x". Needs no templates at all.
local function BuildPlainWindow()
  local frame = CreateFrame("Frame", nil, UIParent)
  Background(frame, 0.85)
  local title = frame:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
  title:SetPoint("TOPLEFT", frame, "TOPLEFT", 12, -8)
  title:SetText("ForeverAH")
  local close = CreateFrame("Button", nil, frame)
  close:SetSize(18, 18)
  close:SetPoint("TOPRIGHT", frame, "TOPRIGHT", -4, -4)
  local x = close:CreateFontString(nil, "OVERLAY", "GameFontNormal")
  x:SetAllPoints()
  x:SetText("x")
  close:SetScript("OnClick", function() ns.ShowWindow(false) end)
  return frame
end

local partial   -- a panel window that failed half way, so it can be hidden

local function BuildPanelWindow()
  local frame = CreateFrame("Frame", nil, UIParent, "BackdropTemplate")
  partial = frame
  frame:SetBackdrop({
    bgFile = "Interface\\Tooltips\\UI-Tooltip-Background", edgeFile = "Interface\\Tooltips\\UI-Tooltip-Border",
    tile = true, tileSize = 16, edgeSize = 14, insets = { left = 3, right = 3, top = 3, bottom = 3 },
  })
  frame:SetBackdropColor(0.04, 0.04, 0.06, 0.94)
  frame:SetBackdropBorderColor(0.5, 0.5, 0.55, 1)

  local bar = frame:CreateTexture(nil, "ARTWORK")   -- a faint gold strip behind the title
  bar:SetPoint("TOPLEFT", frame, "TOPLEFT", 4, -4)
  bar:SetPoint("TOPRIGHT", frame, "TOPRIGHT", -4, -4)
  bar:SetHeight(22)
  bar:SetColorTexture(1, 0.82, 0, 0.10)
  local title = frame:CreateFontString(nil, "OVERLAY", "GameFontNormal")
  title:SetPoint("TOPLEFT", frame, "TOPLEFT", 12, -9)
  title:SetText("ForeverAH")

  local close = CreateFrame("Button", nil, frame, "UIPanelCloseButton")
  close:SetSize(24, 24)
  close:SetPoint("TOPRIGHT", frame, "TOPRIGHT", -2, -3)
  close:SetScript("OnClick", function() ns.ShowWindow(false) end)
  return frame
end

local function BuildWindow()
  local ok, frame = pcall(BuildPanelWindow)
  if not ok then
    ns.uiNote = "plain window: " .. tostring(frame)
    if partial then pcall(partial.Hide, partial) end
    frame = BuildPlainWindow()
  end
  ForeverAHWindow = frame
  frame:SetSize(470, 200)
  frame:SetPoint("CENTER", UIParent, "CENTER", 0, 120)
  frame:SetFrameStrata("HIGH")    -- above the auction house and other panels
  frame:SetToplevel(true)
  Draggable(frame, "window")
  frame:Hide()

  status = frame:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
  status:SetPoint("TOPLEFT", frame, "TOPLEFT", 12, -32)
  status:SetPoint("RIGHT", frame, "RIGHT", -12, 0)
  status:SetJustifyH("LEFT")
  local rule = frame:CreateTexture(nil, "ARTWORK")
  rule:SetPoint("TOPLEFT", frame, "TOPLEFT", 10, -48)
  rule:SetPoint("TOPRIGHT", frame, "TOPRIGHT", -10, -48)
  rule:SetHeight(1)
  rule:SetColorTexture(1, 1, 1, 0.12)

  local since = 0
  frame:SetScript("OnShow", function(self)
    self:Raise()
    status:SetText(StatusText())
  end)
  frame:SetScript("OnUpdate", function(_, elapsed)   -- keeps "next in N min" current while open
    since = since + elapsed
    if since >= 1 then
      since = 0
      status:SetText(StatusText())
    end
  end)

  window = frame
  log = AddLog(frame, -54)   -- last: a half-built window must not swallow messages
end

---------------------------------------------------------------------------------------------
-- Button

local function OnClick(_, mouse)
  if mouse == "RightButton" then
    ns.db.ui.quiet = not ns.db.ui.quiet
    ns.Log(ns.db.ui.quiet and "Quiet mode on - this window will not open by itself"
      or "Quiet mode off - this window opens for scan messages", true)
  else
    ns.ShowWindow(not window:IsShown())
  end
end

local function OnEnter(self)
  if not GameTooltip then return end
  GameTooltip:SetOwner(self, "ANCHOR_LEFT")
  GameTooltip:SetText("ForeverAH")
  GameTooltip:AddLine(StatusText(), 1, 1, 1)
  if unread > 0 then GameTooltip:AddLine(unread .. " unread ledger lines", 1, 0.82, 0) end
  GameTooltip:AddLine("Left-click: open or close the window", 0.7, 0.7, 0.7)
  GameTooltip:AddLine("Right-click: quiet mode on/off", 0.7, 0.7, 0.7)
  GameTooltip:AddLine("Drag: move", 0.7, 0.7, 0.7)
  GameTooltip:Show()
end

local function OnLeave()
  if GameTooltip then GameTooltip:Hide() end
end

local function PlaceOnMinimap(angle)
  local radius = Minimap:GetWidth() / 2 + 5
  button:ClearAllPoints()
  button:SetPoint("CENTER", Minimap, "CENTER", math.cos(math.rad(angle)) * radius, math.sin(math.rad(angle)) * radius)
end

-- A round button on the minimap rim, the way minimap buttons are usually built.
local function BuildMinimapButton()
  local b = CreateFrame("Button", nil, Minimap)
  b:SetSize(31, 31)
  b:SetFrameStrata("MEDIUM")
  b:SetFrameLevel(8)
  b:SetHighlightTexture("Interface\\Minimap\\UI-Minimap-ZoomButton-Highlight")
  local back = b:CreateTexture(nil, "BACKGROUND")
  back:SetSize(24, 24)
  back:SetPoint("CENTER", b, "CENTER", 0, 0)
  back:SetTexture("Interface\\Minimap\\UI-Minimap-Background")
  local icon = b:CreateTexture(nil, "ARTWORK")
  icon:SetSize(18, 18)
  icon:SetPoint("CENTER", b, "CENTER", 0, 0)
  icon:SetTexture("Interface\\Icons\\INV_Misc_Coin_02")
  icon:SetTexCoord(0.07, 0.93, 0.07, 0.93)
  local ring = b:CreateTexture(nil, "OVERLAY")
  ring:SetSize(50, 50)
  ring:SetPoint("TOPLEFT", b, "TOPLEFT", 0, 0)
  ring:SetTexture("Interface\\Minimap\\MiniMap-TrackingBorder")
  count = b:CreateFontString(nil, "OVERLAY", "NumberFontNormalSmall")
  count:SetPoint("BOTTOMRIGHT", b, "BOTTOMRIGHT", 2, -1)

  b:RegisterForClicks("LeftButtonUp", "RightButtonUp")
  b:RegisterForDrag("LeftButton")
  b:SetScript("OnDragStart", function(self)
    self:SetScript("OnUpdate", function()
      local cx, cy = Minimap:GetCenter()
      local x, y = GetCursorPosition()
      local scale = Minimap:GetEffectiveScale()
      ns.db.ui.minimap = math.floor(math.deg(math.atan2(y / scale - cy, x / scale - cx)) % 360 + 0.5)
      PlaceOnMinimap(ns.db.ui.minimap)
    end)
  end)
  b:SetScript("OnDragStop", function(self) self:SetScript("OnUpdate", nil) end)
  button, onMinimap = b, true
  PlaceOnMinimap(215)
end

-- The first version's button: a small free-floating label. Used when there is no minimap.
local function BuildFloatingButton()
  local b = CreateFrame("Button", nil, UIParent)
  b:SetSize(52, 20)
  b:SetPoint("TOPLEFT", UIParent, "TOPLEFT", 20, -160)
  b:SetFrameStrata("MEDIUM")
  Background(b, 0.6)
  count = b:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
  count:SetAllPoints()
  Draggable(b, "button")
  b:RegisterForClicks("LeftButtonUp", "RightButtonUp")
  button, onMinimap = b, false
end

local function BuildButton()
  local ok, err = pcall(BuildMinimapButton)
  if not ok then
    ns.uiNote = (ns.uiNote and ns.uiNote .. "; " or "") .. "floating button: " .. tostring(err)
    BuildFloatingButton()
  end
  ForeverAHButton = button
  button:SetScript("OnClick", OnClick)
  button:SetScript("OnEnter", OnEnter)
  button:SetScript("OnLeave", OnLeave)
  SetCount()
end

---------------------------------------------------------------------------------------------

local ok, err = pcall(function()
  BuildWindow()
  BuildButton()
end)
if not ok then
  log = nil
  ns.uiError = tostring(err)
  if window then pcall(window.Hide, window) end
  if button then pcall(button.Hide, button) end
end

ns.On("PLAYER_LOGIN", function()
  ns.db.uiErr = ns.uiError   -- nil when the window built fine
  ns.db.uiNote = ns.uiNote   -- set when a fallback look was used
  if not log then return end
  if onMinimap then
    PlaceOnMinimap(ns.db.ui.minimap or 215)
  else
    RestorePoint("button", button)
  end
  RestorePoint("window", window)
  window:SetShown(ns.db.ui.shown == true)
end)

-- Until the player has put the window somewhere, open it beside the auction house.
local function BesideAuctionHouse()
  if not (log and AuctionHouseFrame) or ns.db.ui.window then return false end
  window:ClearAllPoints()
  window:SetPoint("TOPLEFT", AuctionHouseFrame, "TOPRIGHT", 8, 0)
  return true
end

ns.On("AUCTION_HOUSE_SHOW", function()
  -- The game builds its AH window on this same event; if ours runs first, look again shortly.
  if not BesideAuctionHouse() then C_Timer.After(0.2, BesideAuctionHouse) end
end)
