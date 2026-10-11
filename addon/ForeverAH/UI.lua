-- UI: a small log window and a button to open and close it, so the addon stays out of the chat
-- frame. Display only. Positions and state are saved in ForeverAHDB.ui.
--   left-click the button    open / close the window
--   right-click the button   quiet mode on/off: in quiet mode the window never opens by itself
--   drag the button or the window to move it
-- The window opens by itself for scan messages and /fah. Ledger lines never open it; while it
-- is closed the button counts them ("FAH 3").
--
-- Built from plain frames and textures, no Blizzard templates, so it does not depend on which
-- templates this client ships. If building it fails anyway, messages go to chat as before and
-- the error is saved in ForeverAHDB.uiErr.

local _, ns = ...

local MAX_LINES = 200
local window, log, button, label
local unread = 0

local function SetLabel()
  label:SetText(unread > 0 and ("FAH " .. unread) or "FAH")
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
    SetLabel()
  end
end

-- Adds a line to the window. Returns false when there is no window, so the caller can fall
-- back to chat. quiet = true: never open the window for this line.
function ns.Log(msg, quiet)
  if not log then return false end
  log:AddMessage(date("%H:%M") .. " " .. msg)
  if not window:IsShown() then
    if quiet or (ns.db and ns.db.ui.quiet) then
      unread = unread + 1
      SetLabel()
    else
      ns.ShowWindow(true)
    end
  end
  return true
end

local function Build()
  button = CreateFrame("Button", "ForeverAHButton", UIParent)
  button:SetSize(52, 20)
  button:SetPoint("TOPLEFT", UIParent, "TOPLEFT", 20, -160)
  button:SetFrameStrata("MEDIUM")
  Background(button, 0.6)
  label = button:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
  label:SetAllPoints()
  SetLabel()
  Draggable(button, "button")
  button:RegisterForClicks("LeftButtonUp", "RightButtonUp")
  button:SetScript("OnClick", function(_, mouse)
    if mouse == "RightButton" then
      ns.db.ui.quiet = not ns.db.ui.quiet
      ns.Log(ns.db.ui.quiet and "quiet mode on - this window will not open by itself"
        or "quiet mode off - this window opens for scan messages", true)
    else
      ns.ShowWindow(not window:IsShown())
    end
  end)
  button:SetScript("OnEnter", function(self)
    if not GameTooltip then return end
    GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
    GameTooltip:SetText("ForeverAH")
    GameTooltip:AddLine("Left-click: open or close the log", 1, 1, 1)
    GameTooltip:AddLine("Right-click: quiet mode on/off", 1, 1, 1)
    GameTooltip:AddLine("Drag: move", 1, 1, 1)
    GameTooltip:Show()
  end)
  button:SetScript("OnLeave", function()
    if GameTooltip then GameTooltip:Hide() end
  end)

  window = CreateFrame("Frame", "ForeverAHWindow", UIParent)
  window:SetSize(440, 150)
  window:SetPoint("TOPLEFT", button, "BOTTOMLEFT", 0, -4)   -- follows the button until dragged itself
  window:SetFrameStrata("MEDIUM")
  Background(window, 0.75)
  Draggable(window, "window")
  window:Hide()

  local title = window:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
  title:SetPoint("TOPLEFT", window, "TOPLEFT", 8, -6)
  title:SetText("ForeverAH")

  local close = CreateFrame("Button", nil, window)
  close:SetSize(18, 18)
  close:SetPoint("TOPRIGHT", window, "TOPRIGHT", -3, -3)
  local x = close:CreateFontString(nil, "OVERLAY", "GameFontNormal")
  x:SetAllPoints()
  x:SetText("x")
  close:SetScript("OnClick", function() ns.ShowWindow(false) end)

  local lines = CreateFrame("ScrollingMessageFrame", nil, window)
  lines:SetPoint("TOPLEFT", window, "TOPLEFT", 8, -22)
  lines:SetPoint("BOTTOMRIGHT", window, "BOTTOMRIGHT", -8, 8)
  lines:SetFontObject(GameFontHighlightSmall)
  lines:SetJustifyH("LEFT")
  lines:SetFading(false)
  lines:SetMaxLines(MAX_LINES)
  lines:EnableMouseWheel(true)
  lines:SetScript("OnMouseWheel", function(self, delta)
    if delta > 0 then self:ScrollUp() else self:ScrollDown() end
  end)
  log = lines   -- only now: a half-built window must not swallow messages
end

local ok, err = pcall(Build)
if not ok then
  log = nil
  ns.uiError = tostring(err)
  if window then pcall(window.Hide, window) end
  if button then pcall(button.Hide, button) end
end

ns.On("PLAYER_LOGIN", function()
  ns.db.uiErr = ns.uiError   -- nil when the window built fine
  if not log then return end
  RestorePoint("button", button)
  RestorePoint("window", window)
  window:SetShown(ns.db.ui.shown == true)
end)
