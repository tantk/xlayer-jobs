import os
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

XLAYER_CHAIN_ID = 196
XLAYER_RPC = os.environ.get("XLAYER_RPC", "https://rpc.xlayer.tech")
ESCROW_CONTRACT = os.environ.get("ESCROW_CONTRACT", "0xe6fbc79de726328335909c001b89b6ef5e94ad6c")
USDT_ADDRESS = os.environ.get("USDT_ADDRESS", "0x779ded0c9e1022225f8e0630b35a9b54be713736")
DB_PATH = Path(os.environ.get("DB_PATH", Path.home() / ".xlayer-jobs" / "jobs.db")).expanduser()
