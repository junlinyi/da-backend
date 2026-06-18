# Video Call Scheduling System Design (Simplified)

> **⚠️ SUPERSEDED & DEAD (as of 2026-06).** This describes a recurring weekly-availability / date-override grid (When2Meet-style) with `user_weekly_availability` / `user_availability_overrides` tables — **none of which exist anymore**. It was superseded first by the legacy two-tier system and then entirely by **SCHEDULING_V2** (24h text window + single-scheduler video date). The canonical, as-built technical reference is [`../DatingAppProj/SCHEDULING_V2.md`](../DatingAppProj/SCHEDULING_V2.md) and the backend overview in [`CLAUDE.md`](CLAUDE.md) (Scheduling V2 section). **Do not implement against this document.** Retained for historical context only.

---


## Core Principles

### 1. **Fixed 15-Minute Calls**
- All calls are exactly 15 minutes
- Extensions handled during call (5 min increments, up to 3 times)
- 30-minute slots accommodate potential extensions

### 2. **Simplified Availability System**

#### **Weekly Default Schedule**
- Sunday-Saturday recurring availability
- Set once during registration/profile setup
- Examples:
  - Monday: 6-10 PM
  - Tuesday: 6-10 PM  
  - Wednesday: 6-10 PM
  - etc.

#### **Date-Specific Overrides**
- Override specific dates with custom time slots
- **No `is_available` boolean** - just time slots
- If a date has 0 available time slots, it's effectively blocked

## How Overrides Work

### **Override Structure**
```sql
-- Date-specific overrides (just time slots)
user_availability_overrides:
- user_id, date, start_time, end_time, reason
```

### **UI/UX Flow**

#### **7-Day Calendar View**
- Show current day + next 6 days
- **Pre-populate with weekly defaults**: Wednesday shows default Wednesday availability
- User can edit any day's time slots
- **Visual indicators**:
  - Default times (gray)
  - Override times (highlighted)
  - No times = blocked day

#### **Override Actions**
1. **Edit Times**: Modify existing time slots
2. **Remove Times**: Deselect slots to block them
3. **Add Times**: Add new available slots
4. **Reset Day**: Remove override, use weekly default

### **Example Scenarios**

#### **Scenario A: Travel Block**
- User normally available Mon-Fri 6-10 PM
- User removes all time slots for March 15-20
- Result: March 15-20 are blocked (0 available slots)

#### **Scenario B: Partial Day Override**
- User normally available Mon 6-10 PM
- User overrides March 18 (Monday) to be available 2-6 PM instead
- Result: March 18 uses 2-6 PM, other days use normal schedule

#### **Scenario C: Event Conflict**
- User normally available Fri 6-10 PM
- User has dinner plans Friday 7-9 PM
- User removes 7-9 PM slot from March 22
- Result: March 22 available 6-7 PM and 9-10 PM

## Timezone Handling

### **Two Scenarios**

#### **1. Existing Scheduled Calls**
- **Keep original UTC times**
- User sees call at original time (may be inconvenient in new timezone)
- **Rationale**: Changing would break existing commitments

#### **2. Future Scheduling**
- **Detect timezone change** via location services
- **Show notification**: "Timezone changed! Update your availability?"
- **Convert availability** to new timezone
- **Examples**:
  - Old: 6-10 PM EST
  - New: 6-10 PM PST (3 hours earlier)
  - System converts: 6-10 PM EST → 3-7 PM PST

### **Implementation**
```python
def handle_timezone_change(user_id: int, new_timezone: str):
    # 1. Detect change
    old_timezone = get_user_timezone(user_id)
    if old_timezone != new_timezone:
        # 2. Show notification
        send_timezone_change_notification(user_id)
        
        # 3. Convert weekly availability
        convert_weekly_availability(user_id, old_timezone, new_timezone)
        
        # 4. Convert upcoming overrides
        convert_upcoming_overrides(user_id, old_timezone, new_timezone)
```

## Implementation Details

### **Database Schema**
```sql
-- Weekly defaults (set once)
user_weekly_availability:
- user_id, day_of_week (0-6), start_time, end_time

-- Date-specific overrides (simplified)
user_availability_overrides:
- user_id, date, start_time, end_time, reason
```

### **API Endpoints**
```
GET /users/{user_id}/availability
- Returns weekly defaults + upcoming overrides
- Pre-populates 7-day view with defaults

POST /users/{user_id}/availability/overrides
- Create/update date-specific time slots

DELETE /users/{user_id}/availability/overrides/{override_id}
- Remove override (revert to weekly default)

POST /users/{user_id}/timezone/update
- Handle timezone change and convert availability
```

### **Scheduling Logic**
```python
def get_available_slots(user_id: int, date: date) -> List[TimeSlot]:
    # Check for override first
    overrides = get_overrides(user_id, date)
    if overrides:
        return overrides  # Use override time slots
    
    # Fall back to weekly default
    day_of_week = date.weekday()
    weekly = get_weekly_availability(user_id, day_of_week)
    return [weekly]  # Use weekly time slot

def is_user_available(user_id: int, date: date, time: time) -> bool:
    available_slots = get_available_slots(user_id, date)
    return any(slot.start_time <= time <= slot.end_time for slot in available_slots)
```

## Benefits of Simplified Design

1. **No Boolean Flags**: Just time slots - cleaner data model
2. **Pre-populated UI**: Users see their current availability
3. **Intuitive**: "Remove time slots" = block that time
4. **Timezone Aware**: Clear handling of location changes
5. **Simple Logic**: No complex availability resolution

## Future Enhancements

1. **Bulk Operations**: "Block all weekends in March"
2. **Template Overrides**: "Business trip" (remove 9-5 for 5 days)
3. **Recurring Overrides**: "Every Monday in March"
4. **Conflict Detection**: Warn about overlapping events 