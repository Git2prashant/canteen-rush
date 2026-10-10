---
name: canteen-preorder
description: Autonomous campus dining pre-order and kitchen queue coordination skill using Gemma 4. Enables conversational food ordering, dietary and budget recommendations, price verification, anti-spam roll number validation, and real-time kitchen queue dispatch.
license: MIT
compatibility: gemma-4-26b-a4b-it, gemma-4-31b-it
metadata:
  version: "1.0.0"
  author: "CanteenRush Team"
  category: "campus-life"
---

# CanteenPreorder Agent Skill

This skill guides an autonomous AI agent (powered by Gemma 4) to act as a campus dining concierge and kitchen queue dispatcher. It bridges the gap between hungry students in lecture halls and busy canteen kitchen staff.

## Core Capabilities

1. **Conversational Pre-Ordering**: Understands natural, messy, or customized student food orders (e.g., "extra spicy Maggi", "less sugar Cold Coffee", "crispy sandwich").
2. **Student Authentication & Anti-Spam**: Verifies student identity via their campus Roll Number against the institutional roster, enforcing a strict 1-active-order limit to eliminate spam.
3. **Menu & Pricing Calculation**: Dynamically queries canteen menu data, verifies availability, and accurately calculates total costs.
4. **Queue ETA Estimation**: Calculates live kitchen workload and estimates wait time, allowing students to pick up food hot without waiting in line.
5. **Kitchen Ticket Dispatch**: Issues unique Token IDs and 4-digit Claim PINs, pushing confirmed orders directly to the kitchen display.

## Registered Tools

The skill requires access to the following deterministic Python functions:

- `get_canteen_menu(category: str)`: Fetches items, prices, and baseline prep times.
- `verify_student(roll_number: str)`: Validates campus roll numbers and retrieves hostel room information.
- `check_kitchen_queue()`: Computes real-time workload (number of cooking vs. ready orders) and average wait times.
- `place_canteen_preorder(student_roll: str, items_summary: str, special_instructions: str, total_bill: int)`: Commits the order to the live kitchen board.
- `calculator(expression: str)`: Provides deterministic math for item quantity and bill calculations.

## Standard Agent Workflow

```
1. Receive Student Query
   │
   ├─► Browse / Recommend:
   │   • Call `get_canteen_menu()`
   │   • Recommend items based on dietary preferences and budget
   │
   ├─► Check Queue Status:
   │   • Call `check_kitchen_queue()`
   │   • Inform student of current prep backlog
   │
   └─► Place Pre-Order:
       • Ensure student Roll Number is captured (call `verify_student`)
       • Calculate exact price using `calculator` or verified menu item costs
       • Call `place_canteen_preorder`
       • Format confirmation: Token Number, 4-digit Claim PIN, ETA, and Counter location
```

## Security & Verification Guidelines

- **Zero External Overhead**: Pickup claim verification uses in-memory 4-digit PINs, avoiding expensive SMS gateways.
- **Pay at Counter**: Informs students to pay via UPI or cash directly at the counter upon presenting their Token and PIN.
- **Quota Resilience**: Uses deterministic tool outputs and local caching to protect Gemini API rate limits on congested campus networks.
