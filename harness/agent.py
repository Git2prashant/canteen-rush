"""The harness loop: the model asks for a tool, we run it, and we give the answer back.

Use it like this:
    from harness import Agent
    agent = Agent(system="You are a helpful assistant.", verbose=True)
    print(agent.run("What is 17 * 23?"))
"""

from google.genai import types

import gemma_client

from . import tools as toolbox


class Agent:
    def __init__(self, system=None, max_steps=5, verbose=False, generate=None):
        self.system = system
        self.max_steps = max_steps  # the most tool rounds before we stop
        self.verbose = verbose  # True prints each step as it happens
        self.generate = generate or gemma_client.generate_raw  # tests swap in a fake
        self.steps = []  # a list a screen can show: {"kind": ..., "text": ...}

    def _log(self, kind, text):
        self.steps.append({"kind": kind, "text": text})
        if self.verbose:
            print(f"[{kind}] {text}")

    def run(self, question):
        self.steps = []
        # `contents` is the whole conversation so far. It grows each round.
        contents = [types.Content(role="user", parts=[types.Part(text=question)])]
        config = types.GenerateContentConfig(
            system_instruction=self.system,
            tools=[types.Tool(function_declarations=toolbox.get_declarations())],
        )

        for _ in range(self.max_steps):
            response = self.generate(contents, config)
            calls = response.function_calls

            # No tool request means the model gave its final answer.
            if not calls:
                answer = response.text or ""
                self._log("answer", answer)
                return answer

            # Keep the model's own turn in the conversation, then answer each request.
            contents.append(response.candidates[0].content)
            replies = []
            for call in calls:
                args = dict(call.args or {})
                self._log("tool_call", f"Model asked to run {call.name} with {args}")
                result = toolbox.run_tool(call.name, args)
                self._log("tool_result", f"Our code returned: {result}")
                reply = types.FunctionResponse(id=call.id, name=call.name, response={"result": result})
                replies.append(types.Part(function_response=reply))
            contents.append(types.Content(role="user", parts=replies))

        message = f"Stopped after {self.max_steps} steps without a final answer. Try a simpler question."
        self._log("stopped", message)
        return message
