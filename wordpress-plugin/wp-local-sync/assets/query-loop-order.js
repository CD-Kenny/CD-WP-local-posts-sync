(function (wp) {
    if (!wp || !wp.blockEditor || !wp.components || !wp.compose || !wp.element || !wp.hooks || !wp.i18n) {
        return;
    }

    const { InspectorControls } = wp.blockEditor;
    const { PanelBody, SelectControl } = wp.components;
    const { createHigherOrderComponent } = wp.compose;
    const { Fragment, createElement } = wp.element;
    const { addFilter } = wp.hooks;
    const { __ } = wp.i18n;

    const DEFAULT_ORDER_BY_OPTIONS = [
        { label: __('Date', 'wp-local-sync'), value: 'date' },
        { label: __('Title', 'wp-local-sync'), value: 'title' },
        { label: __('Menu order', 'wp-local-sync'), value: 'menu_order' },
        { label: __('Last modified', 'wp-local-sync'), value: 'modified' },
        { label: __('Slug', 'wp-local-sync'), value: 'slug' },
        { label: __('Author', 'wp-local-sync'), value: 'author' },
        { label: __('ID', 'wp-local-sync'), value: 'id' },
    ];

    const ORDER_DIRECTION_OPTIONS = [
        { label: __('Ascending', 'wp-local-sync'), value: 'ASC' },
        { label: __('Descending', 'wp-local-sync'), value: 'DESC' },
    ];

    const withQueryLoopMenuOrderControl = createHigherOrderComponent(function (BlockEdit) {
        return function (props) {
            if (props.name !== 'core/query') {
                return createElement(BlockEdit, props);
            }

            const query = props.attributes && props.attributes.query ? props.attributes.query : {};
            const currentOrderBy = query.orderBy || 'date';
            const currentOrder = String(query.order || 'ASC').toUpperCase() === 'DESC' ? 'DESC' : 'ASC';
            const orderByOptions = DEFAULT_ORDER_BY_OPTIONS.some(function (option) {
                return option.value === currentOrderBy;
            })
                ? DEFAULT_ORDER_BY_OPTIONS
                : DEFAULT_ORDER_BY_OPTIONS.concat([
                      {
                          label: currentOrderBy,
                          value: currentOrderBy,
                      },
                  ]);

            return createElement(
                Fragment,
                null,
                createElement(BlockEdit, props),
                props.isSelected
                    ? createElement(
                          InspectorControls,
                          { group: 'settings' },
                          createElement(
                              PanelBody,
                              {
                                  title: __('WP Local Sync', 'wp-local-sync'),
                                  initialOpen: false,
                              },
                              createElement(SelectControl, {
                                  label: __('Order by', 'wp-local-sync'),
                                  value: currentOrderBy,
                                  options: orderByOptions,
                                  help: __('Use menu order for Query Loop blocks when WP Local Sync ordering is enabled.', 'wp-local-sync'),
                                  onChange: function (value) {
                                      props.setAttributes({
                                          query: Object.assign({}, query, {
                                              orderBy: value,
                                          }),
                                      });
                                  },
                              }),
                              createElement(SelectControl, {
                                  label: __('Order direction', 'wp-local-sync'),
                                  value: currentOrder,
                                  options: ORDER_DIRECTION_OPTIONS,
                                  help: __('Choose whether the Query Loop uses ascending or descending menu order.', 'wp-local-sync'),
                                  onChange: function (value) {
                                      props.setAttributes({
                                          query: Object.assign({}, query, {
                                              order: value,
                                          }),
                                      });
                                  },
                              })
                          )
                      )
                    : null
            );
        };
    }, 'withQueryLoopMenuOrderControl');

    addFilter(
        'editor.BlockEdit',
        'wp-local-sync/query-loop-menu-order-control',
        withQueryLoopMenuOrderControl
    );
})(window.wp);