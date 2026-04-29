"""Minimal Gemini example: LangChain ReAct agent with KeeperHub tools.

Prerequisites:
    pip install langchain-keeperhub langchain langchain-google-genai langgraph python-dotenv

Environment variables:
    KEEPERHUB_API_KEY  -- your org-scoped kh_ key
    GOOGLE_API_KEY     -- your Gemini API key
"""

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_google_genai import ChatGoogleGenerativeAI

from langchain_keeperhub import KeeperHubToolkit

load_dotenv()


def main() -> None:
    toolkit = KeeperHubToolkit()  # reads KEEPERHUB_API_KEY from env
    tools = toolkit.get_tools()

    llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0)
    agent = create_agent(model=llm, tools=tools)

    result = agent.invoke(
        {"messages": [("user", "Transfer 2 USDC(0x41E94Eb019C0762f9Bfcf9Fb1E58725BfB0e7582) token to 0x3E67cc2C7fFf86d9870dB9D02c43e789B52FB296 on Polygon Amoy (chain ID: 80002), my wallet address is 0x0c30281118fdfA0e51cd517A38BBFD191C1f9b8a")]}
    )
    print(result["messages"][-1].content)


if __name__ == "__main__":
    main()
