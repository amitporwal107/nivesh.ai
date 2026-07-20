package ai.nivesh.app.ui.risk;

import ai.nivesh.app.data.repo.DashboardsRepository;
import dagger.internal.DaggerGenerated;
import dagger.internal.Factory;
import dagger.internal.QualifierMetadata;
import dagger.internal.ScopeMetadata;
import javax.annotation.processing.Generated;
import javax.inject.Provider;

@ScopeMetadata
@QualifierMetadata
@DaggerGenerated
@Generated(
    value = "dagger.internal.codegen.ComponentProcessor",
    comments = "https://dagger.dev"
)
@SuppressWarnings({
    "unchecked",
    "rawtypes",
    "KotlinInternal",
    "KotlinInternalInJava"
})
public final class RiskViewModel_Factory implements Factory<RiskViewModel> {
  private final Provider<DashboardsRepository> dashboardsProvider;

  public RiskViewModel_Factory(Provider<DashboardsRepository> dashboardsProvider) {
    this.dashboardsProvider = dashboardsProvider;
  }

  @Override
  public RiskViewModel get() {
    return newInstance(dashboardsProvider.get());
  }

  public static RiskViewModel_Factory create(Provider<DashboardsRepository> dashboardsProvider) {
    return new RiskViewModel_Factory(dashboardsProvider);
  }

  public static RiskViewModel newInstance(DashboardsRepository dashboards) {
    return new RiskViewModel(dashboards);
  }
}
