local warmup = tonumber(os.getenv("QUICKSNAPS_WARMUP"))
local after = tonumber(os.getenv("QUICKSNAPS_AFTER"))
local hold = tonumber(os.getenv("QUICKSNAPS_HOLD"))
local button_name = os.getenv("QUICKSNAPS_BUTTON")

local start_time = nil
local field = nil
local state = "warmup"

local function fail(message)
    print("[quicksnaps] " .. message)
    state = "failed"
    manager.machine:exit()
end

local function find_button()
    for _, port in pairs(manager.machine.ioport.ports) do
        for _, candidate in pairs(port.fields) do
            if candidate.name == button_name or candidate.default_name == button_name then
                return candidate
            end
        end
    end
    return nil
end

local function snapshot(filename)
    local screen = manager.machine.screens:at(1)
    if screen == nil then
        fail("machine has no emulated screen")
        return false
    end
    local result = screen:snapshot(filename)
    if result ~= nil then
        fail("unable to write " .. filename .. ": " .. tostring(result.message))
        return false
    end
    return true
end

emu.register_frame_done(function()
    if start_time == nil then
        start_time = manager.machine.time
        field = find_button()
        if field == nil then
            fail("input field not found: " .. button_name)
            return
        end
    end

    local elapsed = (manager.machine.time - start_time):as_double()
    if state == "warmup" and elapsed >= warmup then
        if not snapshot("before.png") then return end
        field:set_value(1)
        state = "pressed"
    elseif state == "pressed" and elapsed >= warmup + hold then
        field:clear_value()
        state = "released"
    elseif state == "released" and elapsed >= warmup + hold + after then
        if not snapshot("after.png") then return end
        state = "done"
        manager.machine:exit()
    end
end, "frame")
