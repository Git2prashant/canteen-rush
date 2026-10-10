"""The tools Gemma 4 is allowed to ask for in CanteenRush.

Each tool is a plain Python function decorated with @tool.
Its description comes from its docstring, and inputs from its type hints.
"""

import ast
import inspect
import operator
import sys
import typing
from datetime import datetime
from pathlib import Path

# Add parent directory to path so we can import canteen_data
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import canteen_data

TOOLS = {}  # tool name -> {"func": the function, "declaration": what we tell the model}

_TYPE_NAMES = {str: "string", int: "integer", float: "number", bool: "boolean"}


def tool(func):
    """Register a function as a tool the model can ask for."""
    hints = typing.get_type_hints(func)
    docstring = inspect.cleandoc(func.__doc__ or "")
    properties, required = {}, []
    for name, param in inspect.signature(func).parameters.items():
        py_type = hints.get(name, str)
        if py_type not in _TYPE_NAMES:
            raise TypeError(f"Tool '{func.__name__}': use str, int, float or bool for '{name}'.")
        lines = [l.strip() for l in docstring.splitlines() if l.strip().startswith(name + ":")]
        description = lines[0].split(":", 1)[1].strip() if lines else name
        properties[name] = {"type": _TYPE_NAMES[py_type], "description": description}
        if param.default is inspect.Parameter.empty:
            required.append(name)

    declaration = {"name": func.__name__, "description": docstring.split("\n\n")[0].replace("\n", " ")}
    if properties:
        declaration["parameters"] = {"type": "object", "properties": properties, "required": required}
    TOOLS[func.__name__] = {"func": func, "declaration": declaration}
    return func


def get_declarations():
    return [t["declaration"] for t in TOOLS.values()]


def _convert(py_type, value):
    """The model sends numbers and text loosely. Turn each value into the type we expect."""
    if py_type is bool and isinstance(value, str):
        return value.strip().lower() == "true"
    return py_type(value)


def run_tool(name, args):
    """Run a tool by name. Always returns text. Problems come back as text starting with 'Error'."""
    if name not in TOOLS:
        return f"Error: there is no tool called '{name}'."
    func = TOOLS[name]["func"]
    hints = typing.get_type_hints(func)
    try:
        clean = {key: _convert(hints.get(key, str), value) for key, value in (args or {}).items()}
        return str(func(**clean))
    except Exception as error:
        return f"Error: {error}"


# ---------------------------------------------------------
# Core CanteenRush Tools
# ---------------------------------------------------------

@tool
def get_canteen_menu(category: str = "all") -> str:
    """Get the live canteen menu items, prices in rupees, prep times, and current stock status (🟢 IN STOCK or 🔴 OUT OF STOCK).

    category: 'all', 'Hot Snacks', 'Quick Bites', 'Beverages', or 'Meals'
    """
    return canteen_data.queue_manager.get_menu_formatted(category)


@tool
def verify_student(roll_number: str) -> str:
    """Verify if a student roll number exists in the college campus database.

    roll_number: Campus student roll number, for example 12240101
    """
    res = canteen_data.verify_student_in_roster(roll_number)
    if res.get("valid"):
        return f"Verified: {res['name']} ({res['roll']}) residing at {res['hostel']}, {res['room']}."
    return f"Verification Failed: {res.get('error')}"


@tool
def check_kitchen_queue() -> str:
    """Check the current canteen kitchen live queue status, cooking orders, and estimated wait time."""
    summary = canteen_data.queue_manager.get_queue_summary()
    return (
        f"Kitchen Queue Status: {summary['cooking_count']} orders currently cooking, "
        f"{summary['ready_count']} orders waiting for pickup. "
        f"Estimated preparation wait time for new orders is ~{summary['estimated_wait_minutes']} minutes."
    )


@tool
def check_item_stock(item_name: str) -> str:
    """Check the LIVE, real-time stock availability of a specific canteen menu item before placing an order.

    item_name: The exact or approximate name of the menu item to check, e.g. 'Chole Bhature', 'Cold Coffee', 'Veg Maggi'
    """
    # Scan menu for the item using name matching
    import re
    target = item_name.strip().lower()
    clean_target = re.sub(r"\s*\(.*?\)", "", target).strip()

    best_match = None
    for cat, items in canteen_data.CANTEEN_MENU.items():
        for it in items:
            it_name_lower = it["name"].strip().lower()
            it_clean = re.sub(r"\s*\(.*?\)", "", it_name_lower).strip()
            if it_name_lower == target or it_clean == clean_target:
                best_match = it
                break
            if target in it_name_lower or it_name_lower in target:
                if best_match is None:
                    best_match = it
        if best_match and best_match["name"].strip().lower() == target:
            break

    if best_match is None:
        return (
            f"Item '{item_name}' was not found in the canteen menu. "
            f"Please call get_canteen_menu() to see all available items."
        )

    status = "🟢 IN STOCK — Available for ordering right now!" if best_match.get("in_stock", True) else "🔴 OUT OF STOCK — Currently unavailable."
    return (
        f"Live Stock Check for '{best_match['name']}': {status} "
        f"| Price: ₹{best_match['price']} | Prep time: {best_match['prep_time']} mins"
    )


@tool
def place_canteen_preorder(student_roll: str, items_summary: str, special_instructions: str, total_bill: int) -> str:
    """Place a confirmed pre-order for a student into the live canteen kitchen queue.

    student_roll: The student's campus roll number (e.g. 12240101)
    items_summary: Summary of food and drink items ordered (e.g. '1x Veg Maggi, 1x Cold Coffee')
    special_instructions: Custom requests (e.g. 'Extra spicy, less ice')
    total_bill: Calculated total price in Indian Rupees (e.g. 90)
    """
    result = canteen_data.queue_manager.place_order(
        student_roll=student_roll,
        items_summary=items_summary,
        special_instructions=special_instructions,
        total_bill=total_bill,
    )
    if not result.get("success"):
        return f"Order Failed: {result.get('error')}"

    return (
        f"Order Placed Successfully! "
        f"Token: #{result['token']} | "
        f"Student: {result['student_name']} | "
        f"Items: {result['items']} | "
        f"Special Request: {result['notes']} | "
        f"Total Bill: ₹{result['total']} | "
        f"ETA: Ready in {result['eta_minutes']} minutes | "
        f"Claim PIN: {result['pin']} | "
        f"Pickup At: {result['pickup_counter']}. "
        f"Tell student to pay via UPI or Cash at the counter upon showing Token and PIN."
    )


# ---------------------------------------------------------
# Utility Tools
# ---------------------------------------------------------

_OPERATORS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod,
}

def _calc(node):
    if isinstance(node, ast.Expression):
        return _calc(node.body)
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        val = _calc(node.operand)
        return -val if isinstance(node.op, ast.USub) else val
    if isinstance(node, ast.BinOp) and type(node.op) in _OPERATORS:
        left, right = _calc(node.left), _calc(node.right)
        return _OPERATORS[type(node.op)](left, right)
    raise ValueError("Only numbers and arithmetic operators allowed.")


@tool
def calculator(expression: str) -> str:
    """Calculate prices, discounts or bill split sums.

    expression: mathematical sum, e.g. 40 + 50
    """
    try:
        res = _calc(ast.parse(expression.strip(), mode="eval"))
        return str(res)
    except Exception as e:
        return f"Error: {e}"


@tool
def get_time() -> str:
    """Get the current time on the campus server."""
    return datetime.now().strftime("%H:%M, %A %d %B %Y")
