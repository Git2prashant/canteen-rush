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
    "4. Use get_canteen_menu to confirm item prices, calculate total bill accurately, and call place_canteen_preorder "
    "to officially register the ticket into the kitchen queue.\n"
    "5. Return a clean, cheerful confirmation showing Token #, Claim PIN, Total Bill, ETA, and Pickup Counter.\n"
    "6. Remind them they can pay at Counter 2 via UPI or Cash upon showing their Token and Claim PIN.\n"
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
"""

with gr.Blocks(title=APP_TITLE, theme=custom_theme, css=CUSTOM_CSS) as demo:
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
                        height=420,
                        label="Gemma 4 Canteen Concierge",
                    )
                    card_output = gr.HTML(label="Order Status Card")

                    with gr.Row():
                        user_input = gr.Textbox(
                            placeholder="e.g., 'Order 1 Veg Maggi and 1 Cold Coffee, extra spicy. Roll: 12240101'",
                            label="Your Message / Pre-Order",
                            scale=4,
                        )
                        send_btn = gr.Button("Send Order 🚀", variant="primary", scale=1)

                    gr.Markdown("#### 💡 Quick Demo Prompts:")
                    with gr.Row():
                        btn_demo1 = gr.Button("🍜 Order Maggi + Cold Coffee", size="sm")
                        btn_demo2 = gr.Button("💰 Suggest meal under ₹70", size="sm")
                        btn_demo3 = gr.Button("⏱️ Check kitchen wait time", size="sm")

                with gr.Column(scale=2):
                    roll_box = gr.Textbox(
                        value="12240101",
                        label="🎓 Your Campus Roll Number",
                        info="Used to authenticate against the student roster (prevents spam)",
                    )
                    tools_box = gr.Textbox(
                        label="⚙️ Gemma 4 Agent Tool Steps (Live)",
                        lines=10,
                        interactive=False,
                        info="Shows function-calling in real-time as Gemma executes your tools",
                    )
                    gr.Markdown(
                        """
                        > [!TIP]
                        > **How it works:**
                        > 1. Chat naturally with **Gemma 4**.
                        > 2. The agent calls `get_canteen_menu`, `verify_student`, and `place_canteen_preorder`.
                        > 3. Your order immediately appears in the **Kitchen Live Board** (Tab 2) with a unique Token and Claim PIN!
                        """
                    )

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
                lambda: "Order 1 Veg Maggi and 1 Cold Coffee with Ice Cream. Make the Maggi extra spicy and less cheese. Roll: 12240101",
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
            menu_rows = []
            for cat, items in canteen_data.CANTEEN_MENU.items():
                for it in items:
                    menu_rows.append([cat, it["name"], f"₹{it['price']}", f"{it['prep_time']} mins", it["desc"]])

            gr.Dataframe(
                headers=["Category", "Item", "Price", "Prep Time", "Description"],
                datatype=["str", "str", "str", "str", "str"],
                value=menu_rows,
                interactive=False,
            )

if __name__ == "__main__":
    print("Starting CanteenRush... Open in your browser: http://127.0.0.1:7860")
    demo.launch(share=False)
