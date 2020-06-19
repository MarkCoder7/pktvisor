"""
Dashboard for pktvisor

 Usage:
   dashboard.py ELASTIC_URL [-v VERBOSITY]
   dashboard.py (-h | --help)

 Options:
   -h --help        Show this screen.
   -v VERBOSITY     How verbose output should be, 0 is silent [default: 1]

"""

from functools import lru_cache
from os.path import dirname, join
import logging
import docopt

import pandas as pd

from bokeh.layouts import column, row
from bokeh.models import ColumnDataSource, PreText, Select
from bokeh.plotting import figure
from bokeh.server.server import Server
from lib.tsdb import Elastic

LOG = logging.getLogger(__name__)

DATA_DIR = join(dirname(__file__), 'daily')

DEFAULT_TICKERS = ['AAPL', 'GOOG', 'INTC', 'BRCM', 'YHOO']

def nix(val, lst):
    return [x for x in lst if x != val]

@lru_cache()
def load_ticker(ticker):
    fname = join(DATA_DIR, 'table_%s.csv' % ticker.lower())
    data = pd.read_csv(fname, header=None, parse_dates=['date'],
                       names=['date', 'foo', 'o', 'h', 'l', 'c', 'v'])
    data = data.set_index('date')
    return pd.DataFrame({ticker: data.c, ticker+'_returns': data.c.diff()})

@lru_cache()
def get_data(t1, t2):
    df1 = load_ticker(t1)
    df2 = load_ticker(t2)
    data = pd.concat([df1, df2], axis=1)
    data = data.dropna()
    data['t1'] = data[t1]
    data['t2'] = data[t2]
    data['t1_returns'] = data[t1+'_returns']
    data['t2_returns'] = data[t2+'_returns']
    return data

# set up widgets

stats = PreText(text='', width=500)
ticker1 = Select(value='AAPL', options=nix('GOOG', DEFAULT_TICKERS))
ticker2 = Select(value='GOOG', options=nix('AAPL', DEFAULT_TICKERS))


ticker3 = Select()

# set up plots

source = ColumnDataSource(data=dict(date=[], t1=[], t2=[], t1_returns=[], t2_returns=[]))
source_static = ColumnDataSource(data=dict(date=[], t1=[], t2=[], t1_returns=[], t2_returns=[]))
tools = 'pan,wheel_zoom,xbox_select,reset'

corr = figure(plot_width=350, plot_height=350,
              tools='pan,wheel_zoom,box_select,reset')
corr.circle('t1_returns', 't2_returns', size=2, source=source,
            selection_color="orange", alpha=0.6, nonselection_alpha=0.1, selection_alpha=0.4)

ts1 = figure(plot_width=900, plot_height=200, tools=tools, x_axis_type='datetime', active_drag="xbox_select")
ts1.line('date', 't1', source=source_static)
ts1.circle('date', 't1', size=1, source=source, color=None, selection_color="orange")

ts2 = figure(plot_width=900, plot_height=200, tools=tools, x_axis_type='datetime', active_drag="xbox_select")
ts2.x_range = ts1.x_range
ts2.line('date', 't2', source=source_static)
ts2.circle('date', 't2', size=1, source=source, color=None, selection_color="orange")

# set up callbacks

def ticker1_change(attrname, old, new):
    ticker2.options = nix(new, DEFAULT_TICKERS)
    update()

def ticker2_change(attrname, old, new):
    ticker1.options = nix(new, DEFAULT_TICKERS)
    update()

def update(selected=None):
    t1, t2 = ticker1.value, ticker2.value

    df = get_data(t1, t2)
    data = df[['t1', 't2', 't1_returns', 't2_returns']]
    source.data = data
    source_static.data = data

    update_stats(df, t1, t2)

    corr.title.text = '%s returns vs. %s returns' % (t1, t2)
    ts1.title.text, ts2.title.text = t1, t2

def update_stats(data, t1, t2):
    stats.text = str(data[[t1, t2, t1+'_returns', t2+'_returns']].describe())

ticker1.on_change('value', ticker1_change)
ticker2.on_change('value', ticker2_change)

def selection_change(attrname, old, new):
    t1, t2 = ticker1.value, ticker2.value
    data = get_data(t1, t2)
    selected = source.selected.indices
    if selected:
        data = data.iloc[selected, :]
    update_stats(data, t1, t2)

source.selected.on_change('indices', selection_change)

def app(doc):
    # set up layout
    widgets = column(ticker1, ticker2, stats)
    main_row = row(corr, widgets)
    series = column(ts1, ts2)
    layout = column(main_row, series)

    # initialize
    update()

    doc.add_root(layout)
    doc.title = "Stocks"

def get_variables(url):
    aggs = {
               "pop_list": {
                   "terms": {"field": "pop.raw", "size": 100}
               },
               "network_list": {
                   "terms": {"field": "network.raw", "size": 100}
               },
               "host_list": {
                   "terms": {"field": "host.raw", "size": 100}
               }
           }
    term_filters = None
    tsdb = Elastic(url)
    result = tsdb.query(None, aggs, term_filters=term_filters)

    for n in result['aggregations']['network_list']['buckets']:
        print('network: ' + n['key'])
    for n in result['aggregations']['pop_list']['buckets']:
        print('pop: ' + n['key'])
    for n in result['aggregations']['host_list']['buckets']:
        print('host: ' + n['key'])

def main():
    opts = docopt.docopt(__doc__, version='1.0')

    if int(opts['-v']) > 1:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    print('Opening Bokeh application on http://localhost:5006/, ELK is at ' + opts['ELASTIC_URL'])

    get_variables(opts['ELASTIC_URL'])

    # Setting num_procs here means we can't touch the IOLoop before now, we must
    # let Server handle that. If you need to explicitly handle IOLoops then you
    # will need to use the lower level BaseServer class.
    server = Server({'/': app}, num_procs=1)
    server.start()

    server.io_loop.start()

if __name__ == "__main__":
    main()