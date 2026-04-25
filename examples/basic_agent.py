"""Minimal Gemini example: LangChain ReAct agent with KeeperHub tools.

Prerequisites:
    pip install langchain-keeperhub langchain-google-genai langgraph python-dotenv

Environment variables:
    KEEPERHUB_API_KEY  -- your org-scoped kh_ key
    GOOGLE_API_KEY     -- your Gemini API key
"""

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.prebuilt import create_react_agent

from langchain_keeperhub import KeeperHubToolkit

load_dotenv()


def main() -> None:
    toolkit = KeeperHubToolkit()  # reads KEEPERHUB_API_KEY from env
    tools = toolkit.get_tools()

    llm = ChatGoogleGenerativeAI(model="gemini-3-flash-preview", temperature=0)
    agent = create_react_agent(llm, tools)

    result = agent.invoke(
        {"messages": [("user", "What blockchain networks does KeeperHub support?")]}
    )
    print(result["messages"][-1].content)


if __name__ == "__main__":
    main()
