"""Export the windowed tensors of a journal training iteration for the Flower clients (which run in a venv without pandapower).

    python -m ai.testbed_models.export_fl_data <A|B|C> <iteration>
"""
import sys

import torch

from ai.testbed_models import journal_model as JM
from ai.testbed_models.paths import ART


def main(top: str, it: int) -> None:
    d, _ = JM.load_data(top, it)
    data, stats = JM.make_data(top, d)
    out = {f: getattr(data, f) for f in ("top_name", "N", "x", "A_id", "A_table", "y", "y_kw", "c", "mask", "y_min", "y_scale", "t_index", "split")}
    p = ART / f"journal_{top}" / f"it{it}"
    p.mkdir(parents=True, exist_ok=True)
    torch.save(out, p / "fl_data.pt")
    print("exported", p / "fl_data.pt")


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]))
