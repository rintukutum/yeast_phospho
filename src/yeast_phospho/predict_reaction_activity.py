import numpy as np
import seaborn as sns
import matplotlib.pyplot as plt
from sklearn.cross_validation import LeaveOneOut
from statsmodels.stats.multitest import multipletests
from yeast_phospho import wd
from yeast_phospho.utils import pearson
from sklearn.linear_model import LinearRegression, Ridge, RidgeCV
from pandas import DataFrame, read_csv, Index

# ---- Import
# Steady-state
r_activity = read_csv('%s/tables/reaction_activity_steady_state.tab' % wd, sep='\t', index_col=0)
k_activity = read_csv('%s/tables/kinase_activity_steady_state.tab' % wd, sep='\t', index_col=0)
tf_activity = read_csv('%s/tables/tf_activity_steady_state.tab' % wd, sep='\t', index_col=0)

r_activity_g = read_csv('%s/tables/reaction_activity_steady_state_with_growth.tab' % wd, sep='\t', index_col=0)
k_activity_g = read_csv('%s/tables/kinase_activity_steady_state_with_growth.tab' % wd, sep='\t', index_col=0)
tf_activity_g = read_csv('%s/tables/tf_activity_steady_state_with_growth.tab' % wd, sep='\t', index_col=0)

# Dynamic
r_activity_dyn = read_csv('%s/tables/reaction_activity_dynamic.tab' % wd, sep='\t', index_col=0)
k_activity_dyn = read_csv('%s/tables/kinase_activity_dynamic.tab' % wd, sep='\t', index_col=0)
t_activity_dyn = read_csv('%s/tables/tf_activity_dynamic.tab' % wd, sep='\t', index_col=0)


# ---- Machine learning setup
lm = LinearRegression()

# ---- Perform predictions
# Steady-state comparisons
steady_state = [
    (k_activity, r_activity, 'steady-state', 'kinase', 'no growth'),
    (tf_activity, r_activity, 'steady-state', 'tf', 'no growth'),
    (k_activity_g, r_activity_g, 'steady-state', 'kinase', 'with growth'),
    (tf_activity_g, r_activity_g, 'steady-state', 'tf', 'with growth')
]

# Dynamic comparisons
dynamic = [
    ((k_activity, r_activity), (k_activity_dyn, r_activity_dyn), 'dynamic', 'kinase', 'no growth'),
    ((tf_activity, r_activity), (t_activity_dyn, r_activity_dyn), 'dynamic', 'tf', 'no growth'),
    ((k_activity_g, r_activity_g), (k_activity_dyn, r_activity_dyn), 'dynamic', 'kinase', 'with growth'),
    ((tf_activity_g, r_activity_g), (t_activity_dyn, r_activity_dyn), 'dynamic', 'tf', 'with growth'),
]


lm_res = []

for xs, ys, condition, feature, growth in steady_state:
    x_features, y_features, samples = list(xs.index), list(ys.index), list(set(xs.columns).intersection(ys.columns))

    x, y = xs.ix[x_features, samples].replace(np.NaN, 0.0).T, ys.ix[y_features, samples].T

    y_pred = DataFrame({samples[test]: dict(zip(*(y_features, lm.fit(x.ix[train], y.ix[train, y_features]).predict(x.ix[test])[0]))) for train, test in LeaveOneOut(len(samples))})

    lm_res.extend([(condition, feature, growth, f, 'features', pearson(ys.ix[f, samples], y_pred.ix[f, samples])[0]) for f in y_features])
    lm_res.extend([(condition, feature, growth, f, 'samples', pearson(ys.ix[y_features, s], y_pred.ix[y_features, s])[0]) for s in samples])

    print '[INFO] %s, %s, %s' % (condition, feature, growth)
    print '[INFO] x_features: %d, y_features: %d, samples: %d' % (len(x_features), len(y_features), len(samples))


for (xs_train, ys_train), (xs_test, ys_test), condition, feature, growth in dynamic:
    x_features, y_features = list(set(xs_train.index).intersection(xs_test.index)), list(set(ys_train.index).intersection(ys_test.index))
    train_samples, test_samples = list(set(xs_train.columns).intersection(ys_train.columns)), list(set(xs_test.columns).intersection(ys_test.columns))

    x_train, y_train = xs_train.ix[x_features, train_samples].replace(np.NaN, 0.0).T, ys_train.ix[y_features, train_samples].T
    x_test, y_test = xs_test.ix[x_features, test_samples].replace(np.NaN, 0.0).T, ys_test.ix[y_features, test_samples].T

    y_pred = DataFrame(lm.fit(x_train, y_train).predict(x_test).T, index=y_features, columns=test_samples)

    lm_res.extend([(condition, feature, growth, f, 'features', pearson(ys_test.ix[f, test_samples], y_pred.ix[f, test_samples])[0]) for f in y_features])
    lm_res.extend([(condition, feature, growth, f, 'samples', pearson(ys_test.ix[y_features, s], y_pred.ix[y_features, s])[0]) for s in test_samples])

    print '[INFO] %s, %s, %s' % (condition, feature, growth)
    print '[INFO] x_features: %d, y_features: %d, train_samples: %d, test_samples: %d' % (len(x_features), len(y_features), len(train_samples), len(test_samples))

lm_res = DataFrame(lm_res, columns=['condition', 'feature', 'growth', 'name', 'type_cor', 'cor'])
lm_res['type'] = lm_res['condition'] + '_' + lm_res['feature'] + '_' + lm_res['type_cor']


# ---- Plot predictions correlations
sns.set_style('ticks')

sns.violinplot(y='type', x='cor', data=lm_res, hue='growth', palette='Paired', orient='h', notch=True)
sns.despine(offset=10, trim=True)
plt.xlabel('pearson correlation')
plt.savefig(wd + 'reports/lm_boxplot_correlations_reactions.pdf', bbox_inches='tight')
plt.close('all')
