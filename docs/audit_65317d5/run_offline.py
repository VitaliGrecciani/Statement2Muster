"""Run existing probes with Stripe lookup blocked at transport boundary."""
import runpy,sys
from unittest.mock import patch
with patch('stripe.checkout.Session.list_line_items',side_effect=RuntimeError('offline synthetic audit: no network')):
 runpy.run_path(sys.argv[1],run_name='__main__')
