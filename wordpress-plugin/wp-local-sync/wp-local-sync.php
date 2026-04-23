<?php
/**
 * Plugin Name: WP Local Sync Bridge
 * Description: REST bridge used by the desktop uploader to sync local image folders with WordPress posts.
 * Version: 0.1.2
 * Author: GitHub Copilot
 */

if (!defined('ABSPATH')) {
    exit;
}

final class WP_Local_Sync_Bridge {
    private const VERSION = '0.1.2';
    private const ROUTE_NAMESPACE = 'wp-local-sync/v1';
    private const META_SOURCE_KEY = '_wp_local_sync_source_key';
    private const META_SOURCE_PATH = '_wp_local_sync_source_path';
    private const META_CHECKSUM = '_wp_local_sync_checksum';
    private const OPTION_ENABLE_ORDER = 'wp_local_sync_enable_order';

    public static function bootstrap(): void {
        add_action('rest_api_init', [self::class, 'register_routes']);
        add_action('admin_init', [self::class, 'register_settings']);
        add_action('admin_init', [self::class, 'maybe_enable_post_order_support']);
        add_action('admin_menu', [self::class, 'register_settings_page']);
        add_action('enqueue_block_editor_assets', [self::class, 'enqueue_block_editor_assets']);
        add_action('pre_get_posts', [self::class, 'apply_frontend_post_order']);
        add_filter('query_loop_block_query_vars', [self::class, 'filter_query_loop_block_query_vars'], 10, 3);
        add_filter('rest_post_collection_params', [self::class, 'filter_rest_post_collection_params']);
    }

    public static function register_routes(): void {
        register_rest_route(
            self::ROUTE_NAMESPACE,
            '/status',
            [
                'methods' => WP_REST_Server::READABLE,
                'callback' => [self::class, 'status'],
                'permission_callback' => [self::class, 'can_edit_posts'],
            ]
        );

        register_rest_route(
            self::ROUTE_NAMESPACE,
            '/terms',
            [
                'methods' => WP_REST_Server::READABLE,
                'callback' => [self::class, 'terms'],
                'permission_callback' => [self::class, 'can_edit_posts'],
            ]
        );

        register_rest_route(
            self::ROUTE_NAMESPACE,
            '/sync-post',
            [
                'methods' => WP_REST_Server::CREATABLE,
                'callback' => [self::class, 'sync_post'],
                'permission_callback' => [self::class, 'can_edit_posts'],
            ]
        );

        register_rest_route(
            self::ROUTE_NAMESPACE,
            '/posts/(?P<id>\d+)',
            [
                'methods' => WP_REST_Server::DELETABLE,
                'callback' => [self::class, 'delete_post'],
                'permission_callback' => [self::class, 'can_edit_posts'],
            ]
        );

        register_rest_route(
            self::ROUTE_NAMESPACE,
            '/posts/order',
            [
                'methods' => WP_REST_Server::CREATABLE,
                'callback' => [self::class, 'update_post_orders'],
                'permission_callback' => [self::class, 'can_edit_posts'],
            ]
        );

        register_rest_route(
            self::ROUTE_NAMESPACE,
            '/export',
            [
                'methods' => WP_REST_Server::READABLE,
                'callback' => [self::class, 'export_posts'],
                'permission_callback' => [self::class, 'can_edit_posts'],
            ]
        );
    }

    public static function can_edit_posts(?WP_REST_Request $request = null): bool {
        return current_user_can('edit_posts');
    }

    public static function register_settings(): void {
        register_setting(
            'wp_local_sync_settings',
            self::OPTION_ENABLE_ORDER,
            [
                'type' => 'boolean',
                'sanitize_callback' => static fn ($value): bool => (bool) $value,
                'default' => false,
            ]
        );
    }

    public static function register_settings_page(): void {
        add_options_page(
            'WP Local Sync',
            'WP Local Sync',
            'manage_options',
            'wp-local-sync',
            [self::class, 'render_settings_page']
        );
    }

    public static function enqueue_block_editor_assets(): void {
        wp_enqueue_script(
            'wp-local-sync-query-loop-order',
            plugins_url('assets/query-loop-order.js', __FILE__),
            ['wp-block-editor', 'wp-components', 'wp-compose', 'wp-element', 'wp-hooks', 'wp-i18n'],
            self::VERSION,
            true
        );
    }

    public static function render_settings_page(): void {
        if (!current_user_can('manage_options')) {
            return;
        }

        ?>
        <div class="wrap">
            <h1>WP Local Sync</h1>
            <form method="post" action="options.php">
                <?php settings_fields('wp_local_sync_settings'); ?>
                <table class="form-table" role="presentation">
                    <tr>
                        <th scope="row">Enable post ordering</th>
                        <td>
                            <label for="wp-local-sync-enable-order">
                                <input
                                    id="wp-local-sync-enable-order"
                                    name="<?php echo esc_attr(self::OPTION_ENABLE_ORDER); ?>"
                                    type="checkbox"
                                    value="1"
                                    <?php checked(self::is_order_enabled()); ?>
                                />
                                Use the synced menu order on home and archive queries.
                            </label>
                        </td>
                    </tr>
                </table>
                <?php submit_button(); ?>
            </form>
        </div>
        <?php
    }

    public static function maybe_enable_post_order_support(): void {
        if (!self::is_order_enabled()) {
            return;
        }

        add_post_type_support('post', 'page-attributes');
    }

    public static function apply_frontend_post_order(WP_Query $query): void {
        if (!self::is_order_enabled()) {
            return;
        }

        if (!is_admin() && $query->is_main_query() && ($query->is_home() || $query->is_archive())) {
            $query->set('orderby', 'menu_order');
            $query->set('order', 'ASC');
        }
    }

    public static function filter_query_loop_block_query_vars(array $query, WP_Block $block, int $page): array {
        unset($page);

        if (!self::is_order_enabled()) {
            return $query;
        }

        $parsed_block = $block->parsed_block;
        $order_by = $parsed_block['attrs']['query']['orderBy'] ?? '';
        if ('menu_order' !== $order_by) {
            return $query;
        }

        $query['orderby'] = 'menu_order';
        $requested_order = strtoupper((string) ($parsed_block['attrs']['query']['order'] ?? $query['order'] ?? 'ASC'));
        $query['order'] = 'DESC' === $requested_order ? 'DESC' : 'ASC';

        return $query;
    }

    public static function filter_rest_post_collection_params(array $params): array {
        if (!self::is_order_enabled()) {
            return $params;
        }

        if (!isset($params['orderby']['enum']) || !is_array($params['orderby']['enum'])) {
            return $params;
        }

        if (!in_array('menu_order', $params['orderby']['enum'], true)) {
            $params['orderby']['enum'][] = 'menu_order';
        }

        return $params;
    }

    public static function status(?WP_REST_Request $request = null): WP_REST_Response {
        $user = wp_get_current_user();

        return new WP_REST_Response(
            [
                'message' => 'WordPress local sync bridge is active.',
                'user' => $user instanceof WP_User ? $user->user_login : '',
                'site_url' => home_url(),
            ],
            200
        );
    }

    public static function terms(WP_REST_Request $request) {
        $taxonomy = sanitize_key((string) $request->get_param('taxonomy'));
        if ($taxonomy === '') {
            $taxonomy = 'category';
        }

        if (!taxonomy_exists($taxonomy)) {
            return new WP_Error('invalid_taxonomy', 'The requested taxonomy does not exist.', ['status' => 400]);
        }

        $terms = get_terms(
            [
                'taxonomy' => $taxonomy,
                'hide_empty' => false,
            ]
        );
        if (is_wp_error($terms)) {
            return $terms;
        }

        $items = [];
        foreach ($terms as $term) {
            $items[] = [
                'id' => (int) $term->term_id,
                'name' => $term->name,
                'slug' => $term->slug,
            ];
        }

        return new WP_REST_Response(['terms' => $items], 200);
    }

    public static function sync_post(WP_REST_Request $request) {
        $payload = $request->get_json_params();
        if (!is_array($payload)) {
            return new WP_Error('invalid_payload', 'The request body must be JSON.', ['status' => 400]);
        }

        $post_type = sanitize_key((string) ($payload['post_type'] ?? 'post'));
        if (!post_type_exists($post_type)) {
            return new WP_Error('invalid_post_type', 'The target post type does not exist.', ['status' => 400]);
        }

        $title = sanitize_text_field((string) ($payload['title'] ?? ''));
        if ($title === '') {
            return new WP_Error('missing_title', 'A post title is required.', ['status' => 400]);
        }

        $post_id = absint($payload['wordpress_id'] ?? 0);
        $source_key = sanitize_text_field((string) ($payload['source_key'] ?? ''));
        $source_path = str_replace('\\', '/', sanitize_text_field((string) ($payload['source_path'] ?? '')));
        $status = sanitize_key((string) ($payload['status'] ?? 'draft'));
        $slug = sanitize_title((string) ($payload['slug'] ?? $title));
        $menu_order = isset($payload['menu_order']) ? intval($payload['menu_order']) : null;

        if ($post_id === 0 && $source_key !== '') {
            $post_id = self::find_post_by_source_key($post_type, $source_key);
        }

        $post_data = [
            'post_type' => $post_type,
            'post_title' => $title,
            'post_status' => $status,
            'post_content' => wp_kses_post((string) ($payload['content'] ?? '')),
            'post_excerpt' => sanitize_textarea_field((string) ($payload['excerpt'] ?? '')),
            'post_name' => $slug,
        ];
        if ($menu_order !== null) {
            $post_data['menu_order'] = $menu_order;
        }
        if ($post_id > 0) {
            $post_data['ID'] = $post_id;
        }

        $saved_post_id = wp_insert_post($post_data, true);
        if (is_wp_error($saved_post_id)) {
            return $saved_post_id;
        }

        if ($source_key !== '') {
            update_post_meta($saved_post_id, self::META_SOURCE_KEY, $source_key);
        }
        if ($source_path !== '') {
            update_post_meta($saved_post_id, self::META_SOURCE_PATH, $source_path);
        }
        if (isset($payload['sync_checksum'])) {
            update_post_meta($saved_post_id, self::META_CHECKSUM, sanitize_text_field((string) $payload['sync_checksum']));
        }

        self::update_post_meta_fields($saved_post_id, $payload['meta'] ?? []);
        $taxonomy = sanitize_key((string) ($payload['taxonomy'] ?? 'category'));
        $term_name = sanitize_text_field((string) ($payload['term_name'] ?? ''));
        $term_result = self::assign_term($saved_post_id, $taxonomy, $term_name);
        if (is_wp_error($term_result)) {
            return $term_result;
        }

        $attachment_id = self::maybe_attach_featured_image($saved_post_id, $payload['image'] ?? null, $title, $post_type);
        if (is_wp_error($attachment_id)) {
            return $attachment_id;
        }

        $post = get_post($saved_post_id);
        if (!$post instanceof WP_Post) {
            return new WP_Error('missing_post', 'The post could not be reloaded after saving.', ['status' => 500]);
        }

        $item = self::build_export_item($post, $taxonomy);
        $item['message'] = $post_id > 0 ? 'Updated WordPress post.' : 'Created WordPress post.';

        return new WP_REST_Response($item, 200);
    }

    public static function update_post_orders(WP_REST_Request $request) {
        $payload = $request->get_json_params();
        if (!is_array($payload)) {
            return new WP_Error('invalid_payload', 'The request body must be JSON.', ['status' => 400]);
        }

        $items = $payload['posts'] ?? null;
        if (!is_array($items)) {
            return new WP_Error('invalid_posts', 'The request must include a posts array.', ['status' => 400]);
        }

        $taxonomy = sanitize_key((string) ($payload['taxonomy'] ?? 'category'));
        $updated_posts = [];
        foreach ($items as $item) {
            if (!is_array($item)) {
                continue;
            }

            $post_id = absint($item['id'] ?? 0);
            if ($post_id === 0) {
                continue;
            }

            $post_data = [
                'ID' => $post_id,
                'menu_order' => intval($item['menu_order'] ?? 0),
            ];
            $updated_post_id = wp_update_post($post_data, true);
            if (is_wp_error($updated_post_id)) {
                return $updated_post_id;
            }

            $source_path = str_replace('\\', '/', sanitize_text_field((string) ($item['source_path'] ?? '')));
            if ($source_path !== '') {
                update_post_meta($post_id, self::META_SOURCE_PATH, $source_path);
            }

            $source_key = sanitize_text_field((string) ($item['source_key'] ?? ''));
            if ($source_key !== '') {
                update_post_meta($post_id, self::META_SOURCE_KEY, $source_key);
            }

            if (isset($item['sync_checksum'])) {
                update_post_meta($post_id, self::META_CHECKSUM, sanitize_text_field((string) $item['sync_checksum']));
            }

            $post = get_post($post_id);
            if ($post instanceof WP_Post) {
                $updated_posts[] = self::build_export_item($post, $taxonomy);
            }
        }

        return new WP_REST_Response(['posts' => $updated_posts], 200);
    }

    public static function delete_post(WP_REST_Request $request) {
        $post_id = absint($request['id']);
        if ($post_id === 0) {
            return new WP_Error('invalid_post_id', 'A valid post ID is required.', ['status' => 400]);
        }

        $deleted = wp_delete_post($post_id, true);
        if (!$deleted) {
            return new WP_Error('delete_failed', 'The post could not be deleted.', ['status' => 500]);
        }

        return new WP_REST_Response(['deleted' => true, 'id' => $post_id], 200);
    }

    public static function export_posts(WP_REST_Request $request): WP_REST_Response {
        $post_type = sanitize_key((string) ($request->get_param('post_type') ?: 'post'));
        $taxonomy = sanitize_key((string) ($request->get_param('taxonomy') ?: 'category'));

        $query = new WP_Query(
            [
                'post_type' => $post_type,
                'post_status' => ['publish', 'draft', 'pending', 'private'],
                'posts_per_page' => -1,
                'orderby' => self::is_order_enabled() ? 'menu_order' : 'date',
                'order' => 'ASC',
            ]
        );

        $items = [];
        foreach ($query->posts as $post) {
            if ($post instanceof WP_Post) {
                $items[] = self::build_export_item($post, $taxonomy);
            }
        }

        return new WP_REST_Response(['posts' => $items], 200);
    }

    private static function find_post_by_source_key(string $post_type, string $source_key): int {
        $query = new WP_Query(
            [
                'post_type' => $post_type,
                'post_status' => 'any',
                'posts_per_page' => 1,
                'fields' => 'ids',
                'meta_query' => [
                    [
                        'key' => self::META_SOURCE_KEY,
                        'value' => $source_key,
                    ],
                ],
            ]
        );

        if (empty($query->posts)) {
            return 0;
        }

        return (int) $query->posts[0];
    }

    private static function update_post_meta_fields(int $post_id, $meta_payload): void {
        if (!is_array($meta_payload)) {
            return;
        }

        foreach ($meta_payload as $meta_key => $meta_value) {
            $sanitized_key = sanitize_key((string) $meta_key);
            if ($sanitized_key === '') {
                continue;
            }

            if (is_array($meta_value) || is_object($meta_value)) {
                update_post_meta($post_id, $sanitized_key, wp_json_encode($meta_value));
                continue;
            }

            update_post_meta($post_id, $sanitized_key, sanitize_text_field((string) $meta_value));
        }
    }

    private static function assign_term(int $post_id, string $taxonomy, string $term_name) {
        if ($term_name === '') {
            return true;
        }
        if (!taxonomy_exists($taxonomy)) {
            return new WP_Error('invalid_taxonomy', 'The target taxonomy does not exist.', ['status' => 400]);
        }

        $term = term_exists($term_name, $taxonomy);
        if (!$term) {
            $term = wp_insert_term($term_name, $taxonomy);
        }
        if (is_wp_error($term)) {
            return $term;
        }

        $term_id = is_array($term) ? (int) $term['term_id'] : (int) $term;
        wp_set_post_terms($post_id, [$term_id], $taxonomy, false);
        return true;
    }

    private static function maybe_attach_featured_image(int $post_id, $image_payload, string $title, string $post_type) {
        if (!is_array($image_payload)) {
            return 0;
        }

        $filename = sanitize_file_name((string) ($image_payload['filename'] ?? 'image.jpg'));
        $data_base64 = (string) ($image_payload['data_base64'] ?? '');
        if ($data_base64 === '') {
            return 0;
        }

        $binary = base64_decode($data_base64, true);
        if ($binary === false) {
            return new WP_Error('invalid_image', 'The image payload could not be decoded.', ['status' => 400]);
        }

        $upload = wp_upload_bits($filename, null, $binary);
        if (!empty($upload['error'])) {
            return new WP_Error('upload_failed', $upload['error'], ['status' => 500]);
        }

        if (!post_type_supports($post_type, 'thumbnail')) {
            add_post_type_support($post_type, 'thumbnail');
        }

        $previous_attachment_id = (int) get_post_thumbnail_id($post_id);

        $mime_type = sanitize_mime_type((string) ($image_payload['mime_type'] ?? ''));
        if ($mime_type === '') {
            $file_type = wp_check_filetype($filename);
            $mime_type = (string) ($file_type['type'] ?? 'image/jpeg');
        }

        $attachment = [
            'post_mime_type' => $mime_type,
            'post_title' => sanitize_text_field($title),
            'post_status' => 'inherit',
        ];
        $attachment_id = wp_insert_attachment($attachment, $upload['file'], $post_id, true);
        if (is_wp_error($attachment_id)) {
            return $attachment_id;
        }

        require_once ABSPATH . 'wp-admin/includes/image.php';
        $metadata = wp_generate_attachment_metadata($attachment_id, $upload['file']);
        wp_update_attachment_metadata($attachment_id, $metadata);
        update_post_meta($attachment_id, '_wp_attachment_image_alt', sanitize_text_field($title));
        set_post_thumbnail($post_id, $attachment_id);
        if ($previous_attachment_id > 0 && $previous_attachment_id !== (int) $attachment_id) {
            wp_delete_attachment($previous_attachment_id, true);
        }
        return $attachment_id;
    }

    private static function build_export_item(WP_Post $post, string $taxonomy): array {
        $post_id = (int) $post->ID;
        $attachment_id = (int) get_post_thumbnail_id($post_id);
        $featured_image_url = $attachment_id > 0 ? (string) wp_get_attachment_url($attachment_id) : '';
        $attachment_mime_type = $attachment_id > 0 ? (string) get_post_mime_type($attachment_id) : '';
        $terms = taxonomy_exists($taxonomy) ? wp_get_post_terms($post_id, $taxonomy, ['fields' => 'names']) : [];
        if (is_wp_error($terms)) {
            $terms = [];
        }

        return [
            'id' => $post_id,
            'title' => html_entity_decode(get_the_title($post_id), ENT_QUOTES),
            'content' => $post->post_content,
            'excerpt' => $post->post_excerpt,
            'slug' => $post->post_name,
            'status' => $post->post_status,
            'post_type' => $post->post_type,
            'menu_order' => (int) $post->menu_order,
            'taxonomy' => $taxonomy,
            'taxonomy_terms' => array_values($terms),
            'source_key' => (string) get_post_meta($post_id, self::META_SOURCE_KEY, true),
            'source_path' => (string) get_post_meta($post_id, self::META_SOURCE_PATH, true),
            'sync_checksum' => (string) get_post_meta($post_id, self::META_CHECKSUM, true),
            'featured_image_url' => $featured_image_url,
            'attachment_id' => $attachment_id,
            'attachment_mime_type' => $attachment_mime_type,
            'modified_gmt' => $post->post_modified_gmt,
            'meta' => self::collect_public_meta($post_id),
        ];
    }

    private static function collect_public_meta(int $post_id): array {
        $all_meta = get_post_meta($post_id);
        $result = [];
        foreach ($all_meta as $key => $values) {
            if (strpos((string) $key, '_') === 0) {
                continue;
            }
            if (!is_array($values) || count($values) === 0) {
                continue;
            }
            $value = count($values) === 1 ? maybe_unserialize($values[0]) : array_map('maybe_unserialize', $values);
            $result[$key] = $value;
        }
        return $result;
    }

    private static function is_order_enabled(): bool {
        return (bool) get_option(self::OPTION_ENABLE_ORDER, false);
    }
}

WP_Local_Sync_Bridge::bootstrap();