"""CanteenRush: Autonomous Campus Pre-Order & Kitchen Queue Agent
Powered by Gemma 4 (gemma-4-26b-a4b-it) through the Gemini API.

Run from the repo root:
    python app.py
Open:
    http://127.0.0.1:7860
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import gradio as gr
import gemma_client
import canteen_data
from harness.agent import Agent

SYSTEM_RULE = (
    "You are CanteenRush AI, the intelligent dining pre-order and kitchen queue assistant "
    "for the IIT Bhilai campus canteen. You are powered by Gemma 4 (model: gemma-4-26b-a4b-it).\n\n"
    "Your responsibilities:\n"
    "1. Help students explore the canteen menu, recommend meals within their budget, and check wait times.\n"
    "2. If a student wants to place an order, make sure you have their campus Roll Number (e.g. 12240101). "
    "If not provided, ask for it politely. If provided, use verify_student to check.\n"
    "3. Smart Item Mapping:\n"
    "   - 'cup coffee', 'cup of coffee', or 'hot coffee' maps to 'Hot Coffee (Cup)' (₹25).\n"
    "   - 'cold coffee' maps to 'Cold Coffee' (₹45), or 'Cold Coffee with Ice Cream' (₹55) if ice cream is requested.\n"
    "   - 'maggie' or 'maggi' maps to 'Veg Maggi' (₹40) unless cheese or egg is specified.\n"
    "   - 'chai' or 'tea' maps to 'Hot Masala Chai' (₹15).\n"
    "4. Stock Availability Awareness:\n"
    "   - When checking the menu with get_canteen_menu, look at the stock status tags.\n"
    "   - If an item is marked '🔴 OUT OF STOCK' (such as Chole Bhature or Sweet Lassi), do NOT place an order for it!\n"
    "   - Instead, politely tell the student that it is currently out of stock and recommend available in-stock alternatives from the same category.\n"
    "5. Culinary Common-Sense & Customization Routing:\n"
    "   - Customizations like 'spicy', 'extra spicy', 'no onions', 'extra cheese' ONLY apply to savory food (Maggi, Sandwiches, Rolls, Parathas, Rice).\n"
    "   - Customizations like 'less sugar', 'extra sweet', 'less ice', 'strong/kadak' ONLY apply to beverages (Coffee, Tea, Lassi, Soda).\n"
    "   - NEVER attach 'spicy' or chili notes to Coffee, Tea, or Lassi! That is absurd.\n"
    "   - If a student orders both a snack AND coffee (e.g., '1 Maggi and 1 Coffee, extra spicy'), apply 'extra spicy' ONLY to the Maggi, leaving the coffee standard!\n"
    "   - If a student orders ONLY a beverage and asks for it 'extra spicy' (e.g., 'Hot coffee with extra spicy'), do NOT place the order! Playfully reject it with friendly campus humor: 'Wait, spicy coffee?! 🌶️☕ The canteen kitchen cannot put chili in your Nescafe! Did you mean extra strong/kadak coffee, or did you want to add a spicy snack like Maggi?'\n"
    "6. Use get_canteen_menu to confirm item prices, calculate total bill accurately, and call place_canteen_preorder "
    "to officially register the ticket into the kitchen queue.\n"
    "7. Return a clean, cheerful confirmation showing Token #, Claim PIN, Total Bill, ETA, and Pickup Counter.\n"
    "8. Remind them they can pay at Counter 2 via UPI or Cash upon showing their Token and Claim PIN.\n"
    "Keep answers friendly, clear, and direct."
)

APP_TITLE = "CanteenRush | Campus Pre-Order & Kitchen Queue Agent"


def student_chat(message: str, roll_no: str, history):
    """Processes student message using Gemma 4 Agent with canteen tools."""
    if not message.strip():
        return history, "", "(No question provided.)", ""

    # Attach roll number if student provided it in the sidebar box and not already in prompt
    full_prompt = message
    if roll_no.strip() and roll_no.strip() not in message:
        full_prompt = f"My Roll Number is {roll_no.strip()}. {message}"

    agent = Agent(system=SYSTEM_RULE)
    try:
        reply = agent.run(full_prompt)
    except Exception as error:
        reply = gemma_client.describe_error(error)

    # Format tool steps for visibility during demo
    steps_log = []
    for i, step in enumerate(agent.steps, 1):
        if step.get("type") == "tool":
            steps_log.append(f"{i}. 🛠️ Called Tool: `{step.get('name')}`({step.get('args')})")
        elif step.get("type") == "tool_result":
            res_preview = str(step.get("result"))[:120].replace("\n", " ")
            steps_log.append(f"   ↳ Result: {res_preview}...")

    tool_display = "\n".join(steps_log) if steps_log else "ℹ️ Direct answer (no tools required)"

    # Format order card highlight if order was placed
    card_html = ""
    for step in agent.steps:
        if step.get("name") == "place_canteen_preorder" and "Order Placed Successfully" in str(step.get("result", "")):
            # Look up the latest order placed
            latest = canteen_data.queue_manager.orders[-1]
            card_html = f"""
            <div style="background: linear-gradient(135deg, #1e3a2f, #122820); border: 2px solid #2ecc71; border-radius: 12px; padding: 18px; color: #ffffff; margin-top: 10px;">
                <h3 style="margin-top: 0; color: #2ecc71;">🎉 Order Dispatched to Kitchen!</h3>
                <div style="display: flex; gap: 20px; flex-wrap: wrap;">
                    <div><strong>Token:</strong> <span style="font-size: 1.3em; color: #f1c40f;">#{latest['token']}</span></div>
                    <div><strong>Claim PIN:</strong> <span style="font-size: 1.3em; color: #e74c3c;">{latest['pin']}</span></div>
                    <div><strong>Total:</strong> ₹{latest['total']}</div>
                    <div><strong>Ready In:</strong> ~{latest['eta_minutes']} mins</div>
                </div>
                <p style="margin-bottom: 0; margin-top: 10px; font-size: 0.9em; opacity: 0.9;">
                    📍 Pick up at <strong>Counter 2 (Express Desk)</strong>. Show PIN to collect!
                </p>
            </div>
            """

    history = history or []
    history.append({"role": "user", "content": message})
    history.append({"role": "assistant", "content": reply})

    return history, "", tool_display, card_html


def refresh_kitchen_board():
    """Returns updated kitchen queue table and summary stats."""
    data = canteen_data.queue_manager.get_kitchen_board_data()
    summary = canteen_data.queue_manager.get_queue_summary()
    stats_text = (
        f"🔥 **{summary['cooking_count']}** Cooking in Kitchen  |  "
        f"🟢 **{summary['ready_count']}** Ready for Pickup  |  "
        f"⏱️ **~{summary['estimated_wait_minutes']} mins** Avg Prep Time"
    )
    return data, stats_text


def refresh_stock_board():
    """Returns live stock board rows."""
    return canteen_data.queue_manager.get_stock_board_data()


def staff_mark_ready(token_str: str):
    """Staff marks order as ready."""
    try:
        clean_token = int(str(token_str).replace("#", "").strip())
        if canteen_data.queue_manager.mark_ready(clean_token):
            return f"✅ Token #{clean_token} marked READY FOR PICKUP!"
        return f"⚠️ Token #{clean_token} not found in active queue."
    except ValueError:
        return "⚠️ Please enter a valid Token number (e.g. 102)."


def staff_mark_collected(token_str: str):
    """Staff marks order as collected."""
    try:
        clean_token = int(str(token_str).replace("#", "").strip())
        if canteen_data.queue_manager.mark_collected(clean_token):
            return f"🎉 Token #{clean_token} completed & archived."
        return f"⚠️ Token #{clean_token} not found in active queue."
    except ValueError:
        return "⚠️ Please enter a valid Token number (e.g. 101)."


def get_item_stock_ui_state(item_name: str):
    """Returns dynamic button and status text for the selected item."""
    if not item_name:
        return (
            gr.update(visible=False),
            "Please select an item from the dropdown.",
        )
    is_in_stock = canteen_data.queue_manager.get_item_stock_status(item_name)
    if is_in_stock:
        return (
            gr.update(value=f"🔴 Mark '{item_name}' as OUT OF STOCK", variant="stop", visible=True),
            f"**Current Status:** 🟢 IN STOCK (Available for students)",
        )
    else:
        return (
            gr.update(value=f"🟢 Mark '{item_name}' as IN STOCK (Available)", variant="primary", visible=True),
            f"**Current Status:** 🔴 OUT OF STOCK (Currently unavailable)",
        )


def toggle_stock_and_refresh(item_name: str):
    """Toggles stock and returns updated UI states for all tables across the app."""
    if not item_name:
        return (
            gr.update(),
            "⚠️ Please select an item.",
            canteen_data.queue_manager.get_stock_board_data(),
            canteen_data.queue_manager.get_menu_ref_data(),
            "⚠️ No item selected.",
        )
    curr_status = canteen_data.queue_manager.get_item_stock_status(item_name)
    new_status = not curr_status
    canteen_data.queue_manager.toggle_item_stock(item_name, new_status)

    btn_update, status_text = get_item_stock_ui_state(item_name)
    stock_board_data = canteen_data.queue_manager.get_stock_board_data()
    menu_ref_data = canteen_data.queue_manager.get_menu_ref_data()
    tag = "🟢 IN STOCK" if new_status else "🔴 OUT OF STOCK"
    feedback = f"✅ Success: '{item_name}' is now marked as {tag}!"

    return btn_update, status_text, stock_board_data, menu_ref_data, feedback




# ---------------------------------------------------------
# Gradio UI Layout
# ---------------------------------------------------------
custom_theme = gr.themes.Soft(
    primary_hue="emerald",
    secondary_hue="amber",
)

CUSTOM_CSS = """
body, .gradio-container {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif !important;
}
.header-box {
    background: linear-gradient(135deg, #064e3b 0%, #022c22 100%);
    border: 1px solid #059669;
    border-radius: 14px;
    padding: 20px 24px;
    color: white;
    margin-bottom: 16px;
    box-shadow: 0 4px 20px rgba(6, 78, 59, 0.25);
}
.header-title {
    font-size: 1.8rem;
    font-weight: 800;
    color: #34d399;
    margin: 0;
}
.badge-pill {
    display: inline-block;
    background: rgba(52, 211, 153, 0.15);
    border: 1px solid #34d399;
    color: #6ee7b7;
    padding: 4px 12px;
    border-radius: 20px;
    font-size: 0.85rem;
    font-weight: 600;
    margin-top: 8px;
}
.prompt-box textarea {
    font-size: 1.05rem !important;
    line-height: 1.55 !important;
    border-radius: 12px !important;
    padding: 14px 16px !important;
    border: 1.5px solid #10b981 !important;
    box-shadow: 0 2px 8px rgba(16, 185, 129, 0.1) !important;
    transition: all 0.2s ease-in-out !important;
}
.prompt-box textarea:focus {
    box-shadow: 0 0 0 3px rgba(16, 185, 129, 0.25) !important;
    border-color: #34d399 !important;
}
"""


with gr.Blocks(title=APP_TITLE) as demo:
    gr.HTML(
        f"""
        <div class="header-box">
            <h1 class="header-title">🍔 {APP_TITLE}</h1>
            <p style="margin: 6px 0 0 0; color: #e2e8f0; font-size: 1rem;">
                Autonomous Campus Dining Pre-Order & Real-Time Kitchen Dispatch · <strong>IIT Bhilai</strong>
            </p>
            <div class="badge-pill">⚡ Powered by Gemma 4 (gemma-4-26b-a4b-it) MoE via Gemini API</div>
        </div>
        """
    )

    with gr.Tabs():
        # TAB 1: Student Order View
        with gr.Tab("📱 Student Pre-Order Assistant"):
            with gr.Row():
                with gr.Column(scale=3):
                    chatbot = gr.Chatbot(
                        height=380,
                        label="Gemma 4 Canteen Concierge",
                    )
                    card_output = gr.HTML(label="Order Status Card")

                    gr.Markdown("##### ⚡ Quick Menu Items (Click to add):")
                    with gr.Row():
                        chip_maggi = gr.Button("+ 🍜 Veg Maggi", size="sm", variant="secondary")
                        chip_sandwich = gr.Button("+ 🥪 Grilled Sandwich", size="sm", variant="secondary")
                        chip_coffee = gr.Button("+ ☕ Hot Coffee", size="sm", variant="secondary")
                        chip_cold_coffee = gr.Button("+ 🧋 Cold Coffee", size="sm", variant="secondary")

                    # FOOD-ONLY CUSTOMIZATION (Hidden until food like Maggi or Sandwich is ordered)
                    with gr.Row(visible=False) as food_custom_row:
                        gr.Markdown("🌶️ **Food Customization:**")
                        chip_spicy = gr.Button("🌶️ Extra Spicy (Food)", size="sm", variant="secondary")
                        chip_cheese = gr.Button("🧀 Extra Cheese", size="sm", variant="secondary")

                    # BEVERAGE-ONLY CUSTOMIZATION (Hidden until coffee/tea is ordered)
                    with gr.Row(visible=False) as bev_custom_row:
                        gr.Markdown("☕ **Beverage Customization:**")
                        chip_strong = gr.Button("☕ Extra Strong / Kadak", size="sm", variant="secondary")
                        chip_sugar = gr.Button("🥛 Less Sugar", size="sm", variant="secondary")

                    user_input = gr.Textbox(
                        lines=3,
                        max_lines=5,
                        placeholder=(
                            "💬 Type your order or question naturally:\n"
                            "• 'Place an order for 1 maggie + 2 cup coffee. Make maggi spicy.'\n"
                            "• 'I have a budget of ₹80. What is quick and filling?'\n"
                            "• 'Check current kitchen wait time.'"
                        ),
                        label="💬 Your Pre-Order / Message (Gemma 4 Command Center)",
                        elem_classes=["prompt-box"],
                    )

                    with gr.Row():
                        send_btn = gr.Button("🚀 Send Order to Gemma 4", variant="primary", scale=4)
                        clear_btn = gr.Button("🧹 Clear", variant="secondary", scale=1)

                    gr.Markdown("#### 💡 Quick Demo Scenarios:")
                    with gr.Row():
                        btn_demo1 = gr.Button("🍜 Order Maggi + 2 Coffees", size="sm")
                        btn_demo2 = gr.Button("💰 Suggest meal under ₹70", size="sm")
                        btn_demo3 = gr.Button("⏱️ Check kitchen wait time", size="sm")

                with gr.Column(scale=2):
                    roll_box = gr.Textbox(
                        value="12240101",
                        label="🎓 Your Campus Roll Number",
                        info="Used to authenticate against the student roster (prevents spam)",
                    )

                    # LIVE STOCK BOARD
                    with gr.Accordion("📋 Live Canteen Stock Board (In Stock vs Out of Stock)", open=True):
                        with gr.Row():
                            gr.Markdown("🟢 *In Stock*  |  🔴 *Out of Stock*")
                            refresh_stock_btn = gr.Button("🔄 Refresh Stock", size="sm", variant="secondary")
                        stock_table = gr.Dataframe(
                            headers=["Item", "Category", "Price", "Live Stock Status", "Prep"],
                            datatype=["str", "str", "str", "str", "str"],
                            value=canteen_data.queue_manager.get_stock_board_data(),
                            interactive=False,
                            label="Live Canteen Stock",
                        )

                    tools_box = gr.Textbox(
                        label="⚙️ Gemma 4 Agent Tool Steps (Live)",
                        lines=6,
                        interactive=False,
                        info="Shows function-calling in real-time as Gemma executes your tools",
                    )

            # Helpers for dynamic contextual customization chips
            def add_chip(current, chip_text):
                cur = (current or "").strip()
                if not cur:
                    return f"Order {chip_text}"
                return f"{cur}, {chip_text}"

            def check_visibility(text):
                t = (text or "").lower()
                has_food = any(f in t for f in ["maggi", "maggie", "sandwich", "roll", "paratha", "samosa", "thali", "rice", "omelette"])
                has_bev = any(b in t for b in ["coffee", "tea", "chai", "lassi", "soda"])
                return gr.update(visible=has_food), gr.update(visible=has_bev)

            def add_food_item(current, item_text):
                updated = add_chip(current, item_text)
                v_food, v_bev = check_visibility(updated)
                return updated, v_food, v_bev

            def add_bev_item(current, item_text):
                updated = add_chip(current, item_text)
                v_food, v_bev = check_visibility(updated)
                return updated, v_food, v_bev

            # Item clicks dynamically show the correct contextual row
            chip_maggi.click(lambda c: add_food_item(c, "1x Veg Maggi"), user_input, [user_input, food_custom_row, bev_custom_row])
            chip_sandwich.click(lambda c: add_food_item(c, "1x Paneer Grilled Sandwich"), user_input, [user_input, food_custom_row, bev_custom_row])
            chip_coffee.click(lambda c: add_bev_item(c, "1x Hot Coffee (Cup)"), user_input, [user_input, food_custom_row, bev_custom_row])
            chip_cold_coffee.click(lambda c: add_bev_item(c, "1x Cold Coffee"), user_input, [user_input, food_custom_row, bev_custom_row])

            # Customization modifier clicks
            chip_spicy.click(lambda c: (c or "").strip() + ", make food extra spicy", user_input, user_input)
            chip_cheese.click(lambda c: (c or "").strip() + ", add extra cheese", user_input, user_input)
            chip_strong.click(lambda c: (c or "").strip() + ", make coffee extra strong", user_input, user_input)
            chip_sugar.click(lambda c: (c or "").strip() + ", less sugar", user_input, user_input)

            # Auto-detect if student types food or drink manually
            user_input.change(check_visibility, user_input, [food_custom_row, bev_custom_row])

            clear_btn.click(
                lambda: ("", gr.update(visible=False), gr.update(visible=False)),
                None,
                [user_input, food_custom_row, bev_custom_row],
            )
            refresh_stock_btn.click(refresh_stock_board, None, stock_table)


            # Button wire-ups
            send_btn.click(
                student_chat,
                [user_input, roll_box, chatbot],
                [chatbot, user_input, tools_box, card_output],
            )
            user_input.submit(
                student_chat,
                [user_input, roll_box, chatbot],
                [chatbot, user_input, tools_box, card_output],
            )

            btn_demo1.click(
                lambda: "Place an order for 1 maggie + 2 cup coffee. Make maggi extra spicy. Roll: 12240101",
                None,
                user_input,
            )
            btn_demo2.click(
                lambda: "I have a budget of ₹70 and need something quick and filling. What do you recommend? Roll: 12240105",
                None,
                user_input,
            )
            btn_demo3.click(
                lambda: "What is the current kitchen queue wait time right now?",
                None,
                user_input,
            )

        # TAB 2: Canteen Kitchen Live Display
        with gr.Tab("🍳 Canteen Kitchen Live Board"):
            with gr.Row():
                stats_display = gr.Markdown(
                    "🔥 **1** Cooking in Kitchen  |  🟢 **1** Ready for Pickup  |  ⏱️ **~6 mins** Avg Prep Time"
                )
                refresh_btn = gr.Button("🔄 Refresh Kitchen Board", size="sm", variant="secondary")

            board_table = gr.Dataframe(
                headers=["Token #", "Student", "Items", "Special Notes", "Bill", "Status", "ETA", "Claim PIN"],
                datatype=["str", "str", "str", "str", "str", "str", "str", "str"],
                value=canteen_data.queue_manager.get_kitchen_board_data(),
                interactive=False,
                label="Active Kitchen Orders Queue (Live Dispatch)",
            )

            gr.Markdown("### 👨‍🍳 Canteen Counter Controls:")
            with gr.Row():
                target_token = gr.Textbox(placeholder="e.g. 102", label="Token Number to Update", scale=2)
                ready_btn = gr.Button("🟢 Mark as Ready for Pickup", variant="primary", scale=2)
                collect_btn = gr.Button("✅ Mark as Collected / Delivered", variant="secondary", scale=2)

            action_status = gr.Textbox(label="Status Message", interactive=False)

            gr.Markdown("### 📦 Canteen Stock Management (Real-Time Availability Toggle):")
            with gr.Row():
                item_select = gr.Dropdown(
                    choices=canteen_data.queue_manager.get_all_item_names(),
                    value="Chole Bhature (2 pcs)",
                    label="Select Menu Item to Manage",
                    scale=2,
                )
                current_status_display = gr.Markdown(
                    "**Current Status:** 🔴 OUT OF STOCK (Currently unavailable)",
                    scale=2,
                )

            stock_toggle_btn = gr.Button(
                value="🟢 Mark 'Chole Bhature (2 pcs)' as IN STOCK (Available)",
                variant="primary",
                size="lg",
            )
            stock_action_status = gr.Textbox(label="Live Update Feedback", interactive=False)

            # Wire-ups for staff controls
            refresh_btn.click(refresh_kitchen_board, None, [board_table, stats_display])
            ready_btn.click(staff_mark_ready, target_token, action_status).then(
                refresh_kitchen_board, None, [board_table, stats_display]
            )
            collect_btn.click(staff_mark_collected, target_token, action_status).then(
                refresh_kitchen_board, None, [board_table, stats_display]
            )

        # TAB 3: Canteen Menu Reference
        with gr.Tab("📋 Canteen Menu & Price Card"):
            gr.Markdown("### 📜 IIT Bhilai Canteen Official Menu")
            menu_table = gr.Dataframe(
                headers=["Category", "Item", "Price", "Stock Status", "Prep Time", "Description"],
                datatype=["str", "str", "str", "str", "str", "str"],
                value=canteen_data.queue_manager.get_menu_ref_data(),
                interactive=False,
            )

        # Dynamic stock state update on dropdown selection
        item_select.change(
            get_item_stock_ui_state,
            item_select,
            [stock_toggle_btn, current_status_display],
        )

        # One-click toggle that flips status AND auto-refreshes all tables across Tab 1, Tab 2, and Tab 3!
        stock_toggle_btn.click(
            toggle_stock_and_refresh,
            item_select,
            [stock_toggle_btn, current_status_display, stock_table, menu_table, stock_action_status],
        )

if __name__ == "__main__":
    print("Starting CanteenRush... Open in your browser: http://127.0.0.1:7860")
    demo.launch(theme=custom_theme, css=CUSTOM_CSS, share=False)

